"""Task 2.3: ``agent.run_costed``, the one costed-call sequence (design D4), against a real engine
and a ``MockTransport``. No tool is involved; the tools' own tests come with the tools."""

import asyncio
import json
import logging
from types import SimpleNamespace

import httpx2
import pytest
from fixture_support import FIXTURE_DIR
from sqlalchemy import text
from usage_support import DbLock, Upstream

from mcp_perplexity_pro import agent as agent_module
from mcp_perplexity_pro.agent import run_costed
from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.engine import create_engine_for, database_path
from mcp_perplexity_pro.storage.migrate import migrate
from mcp_perplexity_pro.storage.projects import get_or_create_project
from mcp_perplexity_pro.storage.session import unit_of_work

KEY = "test-dummy-api-key"
TOOL = "perplexity_ask"
BUSY = 0.4


def fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def serve(name, status=200):
    body = fixture(name)
    return lambda request, n: httpx2.Response(status, json=body)


def serve_body(body, status=200):
    return lambda request, n: httpx2.Response(status, json=body)


def inline(status, **extra):
    return {"id": "resp_inline-1", "status": status, "output": [], **extra}


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder):
        settings = make_settings(db_busy_timeout=BUSY, max_attempts=1)
        migrate(settings)
        engine = create_engine_for(settings)
        upstream = Upstream(responder)
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
        client = PerplexityClient(settings, http=http)
        made.append((http, engine))
        app = SimpleNamespace(settings=settings, client=client, engine=engine)
        return app, upstream, settings

    yield build
    for http, engine in made:
        await http.aclose()
        await engine.dispose()


async def events(app):
    async with app.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT tool, api, status, preset, model, request_id, project_name, "
                "cost_nano_usd, cost_source FROM usage_events ORDER BY id"
            )
        )
        return [tuple(r) for r in rows]


async def project_names(app):
    async with app.engine.connect() as conn:
        return list((await conn.execute(text("SELECT name FROM projects"))).scalars())


async def call(app, *, project="alpha", background=False, preset="fast", **kwargs):
    return await run_costed(
        app,
        tool=TOOL,
        project=project,
        body={"preset": preset, "input": "q", "store": False},
        preset=preset,
        background=background,
        **kwargs,
    )


# --- recorded outcomes ----------------------------------------------------------------------


async def test_a_completed_run_is_one_ok_event_with_its_reported_cost(world):
    app, upstream, _ = await world(serve("agent_fast.json"))
    result = await call(app)
    raw = fixture("agent_fast.json")
    assert result.run.id == raw["id"] and result.project == "alpha"
    assert result.event_status == "ok" and result.latency_ms >= 0
    assert await events(app) == [
        (TOOL, "agent", "ok", "fast", raw["model"], raw["id"], "alpha", 1_250_000, "reported")
    ]
    assert upstream.calls == 1


async def test_the_default_project_is_used_when_none_is_named(world):
    app, _, _ = await world(serve("agent_fast.json"))
    await call(app, project=None)
    assert (await events(app))[0][6] == "default" and await project_names(app) == ["default"]


async def test_an_incomplete_run_is_a_result_recorded_as_unexpected_response(world):
    app, _, _ = await world(serve("agent_incomplete_truncated.json"))
    result = await call(app)
    assert result.run.status == "incomplete" and result.event_status == "unexpected_response"
    (event,) = await events(app)
    assert event[2] == "unexpected_response" and event[7:] == (10_000, "reported")


async def test_an_api_400_is_recorded_with_its_category_and_still_reaches_the_caller(world):
    app, _, _ = await world(serve("agent_structured_bad_root_400.json", 400))
    with pytest.raises(PerplexityError) as info:
        await call(app)
    assert info.value.category == "invalid_request"
    (event,) = await events(app)
    assert (event[2], event[3], event[6], event[7:]) == (
        "invalid_request",
        "fast",
        "alpha",
        (0, "none"),
    )
    assert event[5] is None  # no response id on an error


@pytest.mark.parametrize(
    ("responder", "category"),
    [
        (
            lambda request, n: (_ for _ in ()).throw(httpx2.ReadTimeout("cut", request=request)),
            "network_timeout",
        ),
        (
            lambda request, n: httpx2.Response(503, json={"error": {"message": "down"}}),
            "upstream_failure",
        ),
    ],
    ids=["read timeout", "503"],
)
async def test_a_call_cut_at_the_edge_leaves_one_unknown_cost_failure_event(
    world, responder, category
):
    app, upstream, _ = await world(responder)
    with pytest.raises(PerplexityError) as info:
        await call(app)
    assert info.value.category == category and upstream.calls == 1  # a POST is never replayed
    (event,) = await events(app)
    assert (event[2], event[7:]) == (category, (0, "none"))


async def test_failure_to_a_local_name_check_happens_before_anything(world):
    app, upstream, _ = await world(serve("agent_fast.json"))
    with pytest.raises(PerplexityError) as info:
        await call(app, project="bad name!")
    assert info.value.category == "invalid_request"
    assert upstream.calls == 0 and await events(app) == [] and await project_names(app) == []


# --- statuses other than completed or incomplete --------------------------------------------


async def test_an_inline_failed_200_is_recorded_then_raised_naming_the_status(world):
    body = inline("failed", error={"code": "x", "message": "it broke"})
    app, _, _ = await world(serve_body(body))
    with pytest.raises(PerplexityError) as info:
        await call(app)
    assert info.value.category == "unexpected_response" and "failed" in str(info.value)
    assert "it broke" in str(info.value)
    (event,) = await events(app)
    assert event[2] == "unexpected_response" and event[5] == "resp_inline-1"


async def test_an_in_progress_200_on_a_synchronous_call_records_nothing_and_raises(world):
    app, _, _ = await world(serve_body(inline("in_progress")))
    with pytest.raises(PerplexityError) as info:
        await call(app)
    assert info.value.category == "unexpected_response" and "in_progress" in str(info.value)
    assert await events(app) == []


async def test_a_completed_run_with_an_error_is_recorded_and_raised(world):
    app, _, _ = await world(serve_body(inline("completed", error={"message": "late failure"})))
    with pytest.raises(PerplexityError) as info:
        await call(app)
    assert info.value.category == "unexpected_response" and "completed" in str(info.value)
    (event,) = await events(app)
    assert event[2] == "unexpected_response"


@pytest.mark.parametrize("error", [{}, "", 0])
async def test_any_non_null_error_makes_a_synchronous_run_unexpected(world, error):
    app, _, _ = await world(serve_body(inline("completed", error=error)))
    with pytest.raises(PerplexityError) as info:
        await call(app)
    assert info.value.category == "unexpected_response"
    assert len(await events(app)) == 1


async def test_an_unknown_status_on_a_synchronous_call_is_recorded_and_raised(world):
    app, _, _ = await world(serve_body(inline("paused")))
    with pytest.raises(PerplexityError) as info:
        await call(app)
    assert "paused" in str(info.value)
    assert len(await events(app)) == 1


async def test_the_status_in_the_message_is_redacted_and_cut(world):
    token = "pplx-" + "Qq7_" * 12
    app, _, _ = await world(serve_body(inline(f"{token} " + "s" * 300)))
    with pytest.raises(PerplexityError) as info:
        await call(app)
    assert token not in str(info.value) and "pplx-" not in str(info.value)
    assert len(str(info.value)) < 400


# --- background submit ----------------------------------------------------------------------


async def test_a_queued_background_submit_records_nothing(world):
    app, upstream, _ = await world(serve("agent_background_submit_medium.json"))
    result = await call(app, background=True, preset="medium")
    assert result.run.status == "queued" and result.event_status is None
    assert await events(app) == [] and upstream.calls == 1
    assert await project_names(app) == ["alpha"]  # the project was still committed first


async def test_an_unknown_background_status_records_nothing_and_returns_the_body(world):
    app, _, _ = await world(serve_body(inline("paused")))
    result = await call(app, background=True)
    assert result.run.status == "paused" and result.event_status is None
    assert await events(app) == []


async def test_a_terminal_background_submit_is_recorded_once(world):
    app, _, _ = await world(serve("agent_background_completed.json"))
    result = await call(app, background=True, preset="medium")
    assert result.event_status == "ok"
    (event,) = await events(app)
    assert event[2:4] == ("ok", "medium") and event[7:] == (15_990_000, "reported")


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (inline("failed", error={"message": "x"}), "unexpected_response"),
        (inline("cancelled"), "unexpected_response"),
        (inline("incomplete"), "unexpected_response"),
        (inline("in_progress", error={"message": "x"}), "unexpected_response"),
    ],
    ids=["failed", "cancelled", "incomplete", "any status with an error"],
)
async def test_a_terminal_background_submit_never_raises_and_records_one_event(world, body, status):
    app, _, _ = await world(serve_body(body))
    result = await call(app, background=True)  # the caller (research) decides what to do
    assert result.run.id == "resp_inline-1" and result.event_status == status
    assert [e[2] for e in await events(app)] == [status]


async def test_a_background_api_error_is_recorded_and_raised(world):
    app, _, _ = await world(serve("agent_structured_bad_root_400.json", 400))
    with pytest.raises(PerplexityError):
        await call(app, background=True)
    assert [e[2] for e in await events(app)] == ["invalid_request"]


# --- project resolution ----------------------------------------------------------------------


async def test_a_project_created_before_a_failing_call_survives_it(world):
    app, _, _ = await world(serve("agent_structured_bad_root_400.json", 400))
    with pytest.raises(PerplexityError):
        await call(app, project="research")
    assert await project_names(app) == ["research"]
    assert (await events(app))[0][6] == "research"


async def test_resolve_project_false_creates_nothing_and_records_the_name(world):
    app, _, _ = await world(serve("agent_fast.json"))
    async with unit_of_work(app.engine) as session:
        await get_or_create_project(session, "kept")
    await call(app, project="kept", resolve_project=False)
    assert await project_names(app) == ["kept"]
    assert (await events(app))[0][6] == "kept"


# --- ordering, isolation, cancellation ------------------------------------------------------


async def test_another_connection_can_write_while_the_upstream_call_is_in_flight(world):
    app, upstream, settings = await world(serve("agent_fast.json"))
    seen = []
    inner = upstream.responder

    def during_the_call(request, n):
        lock = DbLock(database_path(settings.data_dir))
        try:
            lock.acquire()  # BEGIN IMMEDIATE with busy_timeout 0: fails if we hold the write lock
            seen.append("acquired")
        finally:
            lock.close()
        return inner(request, n)

    upstream.responder = during_the_call
    await call(app)
    assert seen == ["acquired"]


async def test_the_recorder_runs_with_no_write_unit_open(world, monkeypatch):
    """The ordering test: at the moment the recorder is called the write lock must be free.
    Mutation check (2.3): wrapping the recorder call in ``unit_of_work`` makes this fail."""
    app, _, settings = await world(serve("agent_fast.json"))
    real = agent_module.record_usage
    seen = []

    async def probing(engine, **kwargs):
        lock = DbLock(database_path(settings.data_dir))
        try:
            lock.acquire()
            seen.append(kwargs)
        finally:
            lock.close()
        return await real(engine, **kwargs)

    monkeypatch.setattr(agent_module, "record_usage", probing)
    await call(app)
    (kwargs,) = seen
    assert kwargs["secrets"] == (KEY,)
    assert (
        isinstance(kwargs["usage"], dict) and kwargs["usage"] == fixture("agent_fast.json")["usage"]
    )
    assert kwargs["api"] == "agent" and kwargs["tool"] == TOOL and kwargs["project"] == "alpha"
    assert len(await events(app)) == 1


async def test_the_recorder_inside_an_open_write_unit_loses_the_event(world, caplog):
    """Pins the hazard the order above avoids (the control for the test above)."""
    app, _, _ = await world(serve("agent_fast.json"))
    with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.usage"):
        async with unit_of_work(app.engine):
            result = await call(app, resolve_project=False)
    assert result.event_status == "ok"  # the attempt was made, the store was refused
    assert await events(app) == []


async def test_a_database_locked_past_the_busy_timeout_leaves_the_result_unchanged(world, caplog):
    app, upstream, settings = await world(serve("agent_fast.json"))
    baseline = (await call(app)).run.model_dump()
    assert len(await events(app)) == 1
    lock = DbLock(database_path(settings.data_dir))
    inner = upstream.responder
    upstream.responder = lambda request, n: (lock.acquire(), inner(request, n))[1]
    try:
        with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.usage"):
            locked = await call(app)
    finally:
        lock.close()
    assert locked.run.model_dump() == baseline  # nothing raised, same answer
    assert len(await events(app)) == 1  # the second event was lost, the call was not
    assert KEY not in caplog.text


async def test_a_task_cancelled_mid_call_leaves_no_event_and_no_error(world):
    async def hang(request, n):
        await asyncio.sleep(30)

    app, upstream, _ = await world(hang)
    task = asyncio.create_task(call(app))
    await asyncio.wait_for(upstream.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await events(app) == []
    assert await project_names(app) == ["alpha"]  # resolved before the call, as designed

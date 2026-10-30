"""Task 4.1 (py-decisions-tool): ``decisions.run_decide`` records every request through
``costed.costed_call`` against a real engine and a ``MockTransport``. A decision has no request
id, so the usage dedupe index does not apply and identical calls each store an event."""

import asyncio
import json
import logging
from types import SimpleNamespace

import httpx2
import pytest
from fixture_support import FIXTURE_DIR
from sqlalchemy import text
from usage_support import DbLock, Upstream

from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.decisions import DecideOptions, build_request, run_decide
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.pricing import PRICES_AS_OF
from mcp_perplexity_pro.storage.engine import create_engine_for, database_path
from mcp_perplexity_pro.storage.migrate import migrate
from mcp_perplexity_pro.storage.session import unit_of_work

KEY = "test-dummy-api-key"
BUSY = 0.4
SECRET = "zq-distinctive-state-text-4417"
THREE = json.loads((FIXTURE_DIR / "decisions_three_questions.meta.json").read_text())["request"]
NOUL = {"q": {"type": "noul", "instructions": "y"}}


def fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def serve(name, status=200):
    return lambda request, n: httpx2.Response(status, json=fixture(name))


def serve_body(body, status=200, headers=None):
    return lambda request, n: httpx2.Response(status, json=body, headers=headers)


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder, **settings):
        cfg = make_settings(db_busy_timeout=BUSY, max_attempts=1, **settings)
        migrate(cfg)
        engine = create_engine_for(cfg)
        upstream = Upstream(responder)
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
        client = PerplexityClient(cfg, http=http)
        made.append((http, engine))
        return SimpleNamespace(settings=cfg, client=client, engine=engine), upstream, cfg

    yield build
    for http, engine in made:
        await http.aclose()
        await engine.dispose()


async def events(app):
    async with app.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT tool, api, status, model, preset, request_id, project_name, "
                "input_tokens, output_tokens, total_tokens, cost_nano_usd, cost_source, "
                "price_table FROM usage_events ORDER BY id"
            )
        )
        return [tuple(r) for r in rows]


async def decide(app, *, state="s", questions=None, project="alpha", body=None):
    options = DecideOptions(state=state, questions=questions or NOUL)
    return await run_decide(
        app, project=project, body=body if body is not None else build_request(options)
    )


async def test_one_ok_event_with_tokens_model_and_the_computed_cost(world):
    app, _, _ = await world(serve("decisions_three_questions.json"))
    costed = await decide(app, state=THREE["state"], questions=THREE["questions"])
    assert costed.status == "ok" and costed.project == "alpha"
    (
        (tool, api, status, model, preset, rid, project, tin, tout, ttot, nano, source, table),
    ) = await events(app)
    assert (tool, api, status, model, preset, rid, project) == (
        "perplexity_decide", "decisions", "ok", "pplx-decider-v1.1-27b", None, None, "alpha",
    )  # fmt: skip
    assert (tin, tout, ttot, nano, source, table) == (347, 3, 350, 6940, "computed", PRICES_AS_OF)


async def test_two_identical_calls_store_two_events(world):
    app, _, _ = await world(serve("decisions_noul.json"))
    await decide(app)
    await decide(app)
    assert len(await events(app)) == 2


async def test_a_200_without_usage_is_cost_zero_source_none(world):
    body = fixture("decisions_noul.json")
    del body["usage"]
    app, _, _ = await world(serve_body(body))
    await decide(app)
    ((*_, nano, source, _t),) = await events(app)
    assert (nano, source) == (0, "none")


@pytest.mark.parametrize(
    ("responder", "category"),
    [
        (serve("decisions_129_questions_400.json", 400), "invalid_request"),
        (serve("decisions_unauthenticated_401.json", 401), "authentication"),
        (serve_body({"error": {"message": "slow"}}, 429, {"Retry-After": "600"}), "rate_limited"),
        (serve_body({"error": {"message": "down"}}, 503), "upstream_failure"),
        (
            lambda request, n: (_ for _ in ()).throw(httpx2.ReadTimeout("t", request=request)),
            "network_timeout",
        ),
        (serve_body({"model": "x"}), "unexpected_response"),
    ],
    ids=["400", "401", "429", "503", "timeout", "no-answers"],
)
async def test_each_failure_is_one_event_with_its_category_and_no_cost(world, responder, category):
    app, _, _ = await world(responder)
    with pytest.raises(PerplexityError) as caught:
        await decide(app, body={"model": "m", "state": "s", "questions": {}})
    assert caught.value.category == category
    ((*_, status, _m, _p, _r, _pn, _i, _o, _t, nano, source, _tb),) = await events(app)
    assert (status, nano, source) == (category, 0, "none")


async def test_a_local_validation_failure_records_nothing_and_creates_no_project(world):
    app, upstream, _ = await world(serve("decisions_noul.json"))
    with pytest.raises(PerplexityError):
        await decide(app, state="   ")
    assert upstream.calls == 0 and await events(app) == []
    async with app.engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM projects"))).scalar_one() == 0


async def test_a_project_created_before_a_failing_call_survives_it(world):
    app, _, _ = await world(serve_body({"error": {"message": "down"}}, 503))
    with pytest.raises(PerplexityError):
        await decide(app, project="beta")
    async with unit_of_work(app.engine, write=False) as session:
        row = await session.execute(text("SELECT id FROM projects WHERE name = 'beta'"))
        assert row.first() is not None


async def test_another_connection_can_write_while_the_upstream_call_is_in_flight(world):
    app, upstream, cfg = await world(serve("decisions_noul.json"))
    seen = []
    inner = upstream.responder

    def during(request, n):
        lock = DbLock(database_path(cfg.data_dir))
        try:
            lock.acquire()
            seen.append("acquired")
        finally:
            lock.close()
        return inner(request, n)

    upstream.responder = during
    await decide(app)
    assert seen == ["acquired"]


async def test_a_database_locked_past_the_busy_timeout_leaves_the_result_unchanged(world, caplog):
    app, upstream, cfg = await world(serve("decisions_noul.json"))
    baseline = (await decide(app)).result.model_dump()
    lock = DbLock(database_path(cfg.data_dir))
    inner = upstream.responder
    upstream.responder = lambda request, n: (lock.acquire(), inner(request, n))[1]
    try:
        with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.usage"):
            locked = await decide(app)
    finally:
        lock.close()
    assert locked.result.model_dump() == baseline
    assert len(await events(app)) == 1  # the second event was lost, the call was not
    assert KEY not in caplog.text


async def test_a_task_cancelled_mid_call_leaves_no_event_and_no_error(world):
    async def hang(request, n):
        await asyncio.sleep(30)

    app, upstream, _ = await world(hang)
    task = asyncio.create_task(decide(app))
    await asyncio.wait_for(upstream.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await events(app) == []


async def test_the_state_and_question_text_is_in_no_stored_column_and_no_log(world, caplog):
    app, _, _ = await world(serve("decisions_noul.json"))
    with caplog.at_level(logging.DEBUG):
        await decide(
            app, state=SECRET, questions={SECRET: {"type": "noul", "instructions": SECRET}}
        )
    async with app.engine.connect() as conn:
        rows = await conn.execute(text("SELECT * FROM usage_events"))
        stored = json.dumps([[str(v) for v in r] for r in rows])
    assert SECRET not in stored and SECRET not in caplog.text

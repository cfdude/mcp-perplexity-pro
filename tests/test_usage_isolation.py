"""Task 3.5: recording never disturbs the call it observes (usage-recording "Recording never
disturbs the call", "One event per costed upstream call", "A response is recorded once").

The caller is the TEST-ONLY tool of ``usage_support`` built through ``build_server``; the upstream
is an ``httpx2.MockTransport`` serving recorded fixtures.
"""

import asyncio
import copy
import json
import logging

import httpx2
import pytest
from fastmcp import Client
from fixture_support import FIXTURE_DIR
from sqlalchemy import text
from usage_support import (
    TOOL,
    DbLock,
    Upstream,
    add_test_tool,
    costed_call,
    event_count,
    table_counts,
)

from mcp_perplexity_pro import usage as usage_module
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for, database_path
from mcp_perplexity_pro.storage.migrate import migrate

KEY = "pplx-" + "Zy9_" * 8
BUSY = 0.4  # seconds


def fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def serve(name):
    body = fixture(name)
    return lambda request, n: httpx2.Response(200, json=body)


def distinct_ids(request, n):
    body = fixture("agent_fast.json")
    body["id"] = f"resp_distinct-{n}"
    return httpx2.Response(200, json=body)


def rate_limited(request, n):
    return httpx2.Response(
        429, json={"error": {"message": "slow down"}}, headers={"Retry-After": "3600"}
    )


@pytest.fixture
async def world(make_settings):
    """``build(responder)`` -> (server, engine, upstream, settings); everything is cleaned up."""
    made = []

    async def build(responder, busy=BUSY):
        settings = make_settings(api_key=KEY, db_busy_timeout=busy)
        migrate(settings)
        engine = create_engine_for(settings)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT NOT NULL, "
                    "project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE)"
                )
            )
        upstream = Upstream(responder)
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
        server = build_server(settings, http, engine)
        add_test_tool(server)
        made.append((http, engine))
        return server, engine, upstream, settings

    yield build
    for http, engine in made:
        await http.aclose()
        await engine.dispose()


async def call(server, **arguments):
    async with Client(server) as client:
        return await client.call_tool(TOOL, arguments, raise_on_error=False)


def usage_warnings(caplog):
    return [
        r
        for r in caplog.records
        if r.name == "mcp_perplexity_pro.usage" and r.levelno >= logging.WARNING
    ]


def shape(result):
    return (result.is_error, [c.text for c in result.content], result.structured_content)


# --- isolation --------------------------------------------------------------------------------


async def test_a_locked_database_leaves_the_result_identical(world, caplog):
    server, engine, upstream, settings = await world(serve("agent_fast.json"))
    baseline = shape(await call(server, project="alpha"))
    assert await event_count(engine) == 1 and not baseline[0]

    lock = DbLock(database_path(settings.data_dir))
    # take the write lock at upstream time: after project resolution, before the recorder
    inner = upstream.responder
    upstream.responder = lambda request, n: (lock.acquire(), inner(request, n))[1]
    try:
        with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.usage"):
            locked = shape(await call(server, project="alpha"))
    finally:
        lock.close()
    assert locked == baseline  # byte-identical result, nothing raised into the client
    assert await event_count(engine) == 1  # the second event was lost, the call was not
    (record,) = usage_warnings(caplog)
    assert KEY not in caplog.text and "pplx-" not in caplog.text
    assert "storage_busy" in record.getMessage()


async def test_a_parser_that_raises_never_reaches_the_tool(world, caplog, monkeypatch):
    server, engine, upstream, _ = await world(distinct_ids)
    baseline = shape(await call(server, project="alpha"))

    def boom(_usage):
        raise RuntimeError(f"parser bug {KEY}")

    monkeypatch.setattr(usage_module, "usage_from_agent_response", boom)
    with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.usage"):
        patched = shape(await call(server, project="beta"))
    assert patched == baseline
    assert len(usage_warnings(caplog)) == 1
    assert KEY not in caplog.text and "pplx-" not in caplog.text
    assert await event_count(engine) == 2  # the event is still stored, unpriced
    async with engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT cost_source FROM usage_events ORDER BY id DESC"))
        ).first()
    assert row[0] == "none"


async def test_a_tool_failing_after_its_own_write_keeps_only_the_usage_event(world):
    server, engine, _, _ = await world(serve("agent_fast.json"))
    result = await call(server, project="alpha", write_note=True, fail_after_write=True)
    assert result.is_error and result.structured_content["category"] == "internal_error"
    counts = await table_counts(engine, "notes", "usage_events", "projects")
    assert counts["notes"] == 0  # the tool's own write rolled back
    assert counts["usage_events"] == 1  # the spend did not
    assert counts["projects"] == 1  # the project resolved before the call survives (empty)


async def test_a_failure_that_does_not_roll_back_is_the_control(world):
    server, engine, _, _ = await world(serve("agent_fast.json"))
    result = await call(server, project="alpha", write_note=True)
    assert not result.is_error
    counts = await table_counts(engine, "notes", "usage_events")
    assert (counts["notes"], counts["usage_events"]) == (1, 1)


async def test_an_upstream_error_is_recorded_with_its_category_and_still_reaches_the_client(world):
    server, engine, _, _ = await world(rate_limited)
    result = await call(server, project="alpha")
    assert result.is_error and result.structured_content["category"] == "rate_limited"
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status, cost_nano_usd, cost_source, usage_json FROM usage_events")
            )
        ).one()
    assert tuple(row) == ("rate_limited", 0, "none", None)


async def test_two_upstream_calls_with_distinct_ids_store_two_events(world):
    server, engine, upstream, _ = await world(distinct_ids)
    result = await call(server, project="alpha", calls=2)
    assert not result.is_error and upstream.calls == 2
    async with engine.connect() as conn:
        ids = sorted((await conn.execute(text("SELECT request_id FROM usage_events"))).scalars())
    assert ids == ["resp_distinct-1", "resp_distinct-2"]


async def test_a_queued_submit_records_nothing_and_the_completed_poll_is_stored_once(world):
    server, engine, upstream, _ = await world(serve("agent_background_submit.json"))
    result = await call(server, project="alpha")
    assert not result.is_error and await event_count(engine) == 0  # never recorded as ok

    upstream.responder = serve("agent_background_poll_pending.json")
    await call(server, project="alpha")
    assert await event_count(engine) == 0

    upstream.responder = serve("agent_background_poll.json")
    await call(server, project="alpha")
    await call(server, project="alpha")  # polled again: the same response id
    assert await event_count(engine) == 1
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT status, cost_nano_usd FROM usage_events"))).one()
    assert tuple(row) == ("ok", 1_050_000)


# --- cancellation -----------------------------------------------------------------------------


async def test_cancelling_during_the_write_still_stores_the_event(world, monkeypatch):
    server, engine, upstream, settings = await world(serve("agent_fast.json"), busy=10.0)
    app = server.app
    # Signal from inside the recorder, not a sleep: the event is set the moment the recorder
    # opens its unit of work, and the held lock guarantees the write cannot finish before the
    # cancel is delivered. The busy timeout is wide (10 s) so a slow loop cannot run it out.
    recorder_started = asyncio.Event()
    real_unit_of_work = usage_module.unit_of_work

    def signalling(*args, **kwargs):
        recorder_started.set()
        return real_unit_of_work(*args, **kwargs)

    monkeypatch.setattr(usage_module, "unit_of_work", signalling)
    lock = DbLock(database_path(settings.data_dir))
    inner = upstream.responder
    upstream.responder = lambda request, n: (lock.acquire(), inner(request, n))[1]
    task = asyncio.create_task(costed_call(app.engine, app.client, (KEY,), project="alpha"))
    try:
        await asyncio.wait_for(recorder_started.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)  # deliver the cancel while the lock is still held
        lock.release()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
    finally:
        lock.close()
    assert await event_count(engine) == 1


async def test_cancelling_while_the_upstream_call_is_in_flight_stores_nothing(world):
    async def hang(request, n):
        await asyncio.sleep(30)

    server, engine, upstream, _ = await world(hang)
    app = server.app
    task = asyncio.create_task(costed_call(app.engine, app.client, (KEY,), project="alpha"))
    await asyncio.wait_for(upstream.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await event_count(engine) == 0


async def test_costed_call_raises_the_upstream_category_after_recording(world):
    server, engine, _, _ = await world(rate_limited)
    app = server.app
    with pytest.raises(PerplexityError) as caught:
        await costed_call(app.engine, app.client, (KEY,), project="alpha")
    assert caught.value.category == "rate_limited"
    assert await event_count(engine) == 1


def test_the_support_responses_are_copies_not_shared_state():
    assert copy.deepcopy(fixture("agent_fast.json")) == fixture("agent_fast.json")

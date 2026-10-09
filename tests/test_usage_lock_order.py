"""Task 3.6: the write-lock ordering hazard and the correct order (usage-recording "Recording
order"; local-storage "All-or-nothing tool calls" and its "Write lock not held across the call")."""

import asyncio
import json
import logging
import time

import httpx2
import pytest
from fixture_support import FIXTURE_DIR
from sqlalchemy import text
from usage_support import TOOL, Upstream, add_test_tool, costed_call, event_count, table_counts

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate
from mcp_perplexity_pro.storage.projects import get_or_create_project
from mcp_perplexity_pro.storage.session import unit_of_work
from mcp_perplexity_pro.usage import record_usage

BUSY = 0.4
MARGIN = 1.5


def agent_fast(request, n):
    return httpx2.Response(200, json=json.loads((FIXTURE_DIR / "agent_fast.json").read_text()))


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder):
        settings = make_settings(db_busy_timeout=BUSY)
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
        return server, engine, upstream

    yield build
    for http, engine in made:
        await http.aclose()
        await engine.dispose()


async def test_the_recorder_inside_an_open_write_unit_loses_the_event_within_the_timeout(
    world, caplog
):
    """The WRONG order, pinned: the recorder would wait for a lock its own caller holds."""
    server, engine, _ = await world(agent_fast)
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.usage"):
        async with unit_of_work(engine) as session:  # the tool's own write unit, still open
            project = await get_or_create_project(session, "alpha")
            stored = await record_usage(
                engine, tool=TOOL, api="agent", project="alpha", secrets=["test-dummy-api-key"]
            )
            await session.execute(
                text("INSERT INTO notes (body, project_id) VALUES ('mine', :p)"),
                {"p": project.id},
            )
    elapsed = time.monotonic() - started
    assert stored is False
    assert BUSY <= elapsed < BUSY + MARGIN  # waited the busy timeout, then gave up
    assert await event_count(engine) == 0  # nothing stored
    (record,) = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert "storage_busy" in record.getMessage() and "test-dummy-api-key" not in caplog.text
    counts = await table_counts(engine, "notes", "projects")
    assert (counts["notes"], counts["projects"]) == (1, 1)  # the tool's own write committed


async def test_the_correct_order_stores_the_event_and_the_tools_own_record(world):
    server, engine, upstream = await world(agent_fast)
    app = server.app
    # validate, resolve in a committed unit, upstream call, record, then the tool's own write
    result = await costed_call(app.engine, app.client, (), project="alpha", write_note=True)
    assert result == "done:completed" and upstream.calls == 1
    counts = await table_counts(engine, "notes", "usage_events")
    assert (counts["notes"], counts["usage_events"]) == (1, 1)


async def test_another_connection_can_write_while_the_upstream_call_is_in_flight(world):
    async def slow(request, n):
        await asyncio.sleep(BUSY * 3)  # longer than the busy timeout
        return agent_fast(request, n)

    server, engine, upstream = await world(slow)
    app = server.app
    task = asyncio.create_task(
        costed_call(app.engine, app.client, (), project="alpha", write_note=True)
    )
    await asyncio.wait_for(upstream.started.wait(), 5)
    started = time.monotonic()
    async with unit_of_work(engine) as session:  # a write by another call, mid-upstream-call
        await get_or_create_project(session, "bystander")
    assert time.monotonic() - started < BUSY  # no waiting: the tool holds no write unit
    assert await task == "done:completed"
    counts = await table_counts(engine, "notes", "usage_events", "projects")
    assert (counts["notes"], counts["usage_events"], counts["projects"]) == (1, 1, 2)

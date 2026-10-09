"""A TEST-ONLY caller of the usage recorder, built through the production server factory.

``costed_call`` follows the caller pattern of design D7 in its required order: validate the
project name, resolve the project in a unit of work that has committed, make the upstream call,
record, then run the tool's own write. ``add_test_tool`` registers it as the tool ``test_costed``;
no production tool is needed for the recorder's scenarios to be proven.

Do not use ``from __future__ import annotations`` here: FastMCP reads tool annotations at
registration time.
"""

import asyncio
import sqlite3
import time
from collections import Counter
from pathlib import Path

import httpx2
from fastmcp import Context, FastMCP
from sqlalchemy import text

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.projects import (
    DEFAULT_PROJECT,
    get_or_create_project,
    validate_project_name,
)
from mcp_perplexity_pro.storage.session import unit_of_work
from mcp_perplexity_pro.usage import agent_response_status, record_usage

TOOL = "test_costed"


def ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


async def costed_call(
    engine,
    client,
    secrets,
    *,
    project=None,
    calls=1,
    write_note=False,
    fail_after_write=False,
    path="/v1/agent",
    preset="fast",
    tool=TOOL,
) -> str:
    """One tool call: ``calls`` upstream calls, each recorded, then an optional own write."""
    name = validate_project_name(project or DEFAULT_PROJECT)  # pure
    async with unit_of_work(engine) as session:  # short; committed before the upstream call
        await get_or_create_project(session, name)
    body = {}
    for _ in range(calls):
        started = time.monotonic()
        try:
            body = await client.request_json("POST", path, json={"preset": preset, "input": "q"})
        except PerplexityError as exc:
            await record_usage(
                engine,
                tool=tool,
                api="agent",
                status=exc.category,
                project=name,
                latency_ms=ms(started),
                secrets=secrets,
            )
            raise
        status = agent_response_status(body)
        if status is not None:  # None: queued or in progress, nothing to record
            await record_usage(
                engine,
                tool=tool,
                api="agent",
                status=status,
                usage=body.get("usage"),  # the raw mapping: record_usage parses it
                model=body.get("model"),
                preset=preset,
                request_id=body.get("id"),
                project=name,
                latency_ms=ms(started),
                secrets=secrets,
            )
    if write_note:
        async with unit_of_work(engine) as session:  # the tool's own writes, last
            project_row = await get_or_create_project(session, name)
            await session.execute(
                text("INSERT INTO notes (body, project_id) VALUES ('n', :p)"),
                {"p": project_row.id},
            )
            if fail_after_write:
                raise RuntimeError("the tool failed after its own write")
    return f"done:{body.get('status')}"


def add_test_tool(server: FastMCP) -> None:
    @server.tool(name=TOOL)
    async def test_costed(
        ctx: Context,
        project: str | None = None,
        calls: int = 1,
        write_note: bool = False,
        fail_after_write: bool = False,
    ) -> str:
        app = ctx.lifespan_context
        return await costed_call(
            app.engine,
            app.client,
            (app.settings.api_key.get_secret_value(),),
            project=project,
            calls=calls,
            write_note=write_note,
            fail_after_write=fail_after_write,
        )


class DbLock:
    """Holds SQLite's write lock from a second connection (``BEGIN IMMEDIATE``)."""

    def __init__(self, db_file: Path) -> None:
        self._conn = sqlite3.connect(db_file, isolation_level=None)
        self.held = False

    def acquire(self) -> None:
        self._conn.execute("PRAGMA busy_timeout=0")
        self._conn.execute("BEGIN IMMEDIATE")
        self.held = True

    def release(self) -> None:
        if self.held:
            self._conn.execute("ROLLBACK")
            self.held = False

    def close(self) -> None:
        self.release()
        self._conn.close()


class Upstream:
    """A scriptable MockTransport handler: serves ``responder(request, n)`` and counts calls."""

    def __init__(self, responder) -> None:
        self.responder = responder
        self.calls = 0
        self.started = asyncio.Event()

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        self.started.set()
        result = self.responder(request, self.calls)
        if hasattr(result, "__await__"):
            result = await result
        return result


async def event_count(engine) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(text("SELECT count(*) FROM usage_events"))).scalar_one()


async def table_counts(engine, *tables) -> Counter:
    counts = Counter()
    async with engine.connect() as conn:
        for table in tables:
            counts[table] = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
    return counts

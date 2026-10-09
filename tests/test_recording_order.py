"""Task 5.2: the recording order of every costed tool, proven per tool and not only on the helper.

The four costed paths are ask, a chat send, a research submit (answered terminal, so it is a
costed call) and a jobs observation. For each:

* another connection can write while the upstream call is in flight (no write unit is open);
* the usage event is stored after the call and BEFORE the tool's own write (the statement trace
  puts ``usage_events`` between the request and the tool's own table);
* a failing own write keeps the event (not for ask, which has no write after its call);
* a database locked past the busy timeout at recording time leaves the tool's result unchanged.

Mutation check (docs/lessons/cleanup-tests-must-fail-when-cleanup-is-removed.md): moving the
recorder inside an open write unit, in ``run_costed`` (ask, chat, research) or in
``observe_job`` (jobs), turns these tests red.
"""

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

import httpx2
import pytest
from agent_support import fixture, respond_with
from chat_support import FIRST
from research_support import COMPLETED, RUN_ID, Clock, job, routes, seed_job
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from usage_support import DbLock

from mcp_perplexity_pro.storage.engine import database_path

BUSY = 0.3
USAGE_INSERT = "INSERT INTO usage_events"


@dataclass(frozen=True)
class Case:
    name: str
    tool: str
    arguments: dict[str, Any]
    responder: Any  # a factory: each world gets its own
    own_write: str | None  # the tool's own write, after the call (None: it has none)
    seeded: bool = False  # a job row exists before the call


def completed_submit():
    return lambda request, n: httpx2.Response(200, json=fixture(COMPLETED))


CASES = [
    Case(
        "ask",
        "perplexity_ask",
        {"query": "q"},
        lambda: respond_with("agent_fast.json"),
        None,
    ),
    Case(
        "chat",
        "perplexity_chat",
        {"action": "send", "message": FIRST, "title": "Teal"},
        lambda: respond_with("agent_chat_turn_a.json"),
        "INSERT INTO chats",
    ),
    Case(
        "research",
        "perplexity_research",
        {"query": "q"},
        completed_submit,
        "INSERT INTO research_jobs",
    ),
    Case(
        "jobs",
        "perplexity_jobs",
        {"action": "status", "job_id": 1},
        lambda: routes(get=[COMPLETED]),
        "UPDATE research_jobs",
        seeded=True,
    ),
]
WITH_OWN_WRITE = [c for c in CASES if c.own_write]
ids = lambda cases: [c.name for c in cases]  # noqa: E731


async def build(research_world, case: Case, **settings):
    w = await research_world(case.responder(), clock=Clock(), **settings)
    if case.seeded:
        await seed_job(w, response_id=RUN_ID)
    return w


def trace_statements(w, trace: list[str], prefixes: tuple[str, ...]) -> None:
    """Append the (normalized) start of each statement that begins with one of ``prefixes``."""

    @event.listens_for(w.engine.sync_engine, "before_cursor_execute")
    def seen(conn, cursor, statement, parameters, context, executemany):
        head = " ".join(statement.split())
        for prefix in prefixes:
            if head.upper().startswith(prefix.upper()):
                trace.append(prefix)


def mark_requests(w, trace: list[str]) -> None:
    inner = w.upstream.responder
    w.upstream.responder = lambda request, n: (trace.append("HTTP"), inner(request, n))[1]


def fail_statements(w, prefix: str) -> None:
    """Fail every statement starting with ``prefix`` as a busy database does at the driver."""

    @event.listens_for(w.engine.sync_engine, "before_cursor_execute")
    def boom(conn, cursor, statement, parameters, context, executemany):
        if " ".join(statement.split()).upper().startswith(prefix.upper()):
            raise OperationalError(
                statement, parameters, sqlite3.OperationalError("database is locked")
            )


@pytest.mark.parametrize("case", CASES, ids=ids(CASES))
async def test_another_connection_can_write_while_the_upstream_call_is_in_flight(
    research_world, case
):
    w = await build(research_world, case)
    inner = w.upstream.responder
    seen: list[str] = []

    def during(request, n):
        lock = DbLock(database_path(w.settings.data_dir))
        try:
            lock.acquire()  # BEGIN IMMEDIATE with no wait: fails if the tool holds a write unit
            seen.append("free")
        except sqlite3.OperationalError:
            seen.append("blocked")
        finally:
            lock.close()
        return inner(request, n)

    w.upstream.responder = during
    result = await w.call(case.tool, **case.arguments)
    assert not result.is_error, result.content
    assert seen == ["free"]
    assert await w.count("usage_events") == 1


@pytest.mark.parametrize("case", CASES, ids=ids(CASES))
async def test_the_event_is_stored_after_the_call_and_before_the_tools_own_write(
    research_world, case
):
    w = await build(research_world, case)
    trace: list[str] = []
    own = (case.own_write,) if case.own_write else ()
    trace_statements(w, trace, ("INSERT INTO projects", USAGE_INSERT, *own))
    mark_requests(w, trace)
    result = await w.call(case.tool, **case.arguments)
    assert not result.is_error, result.content
    expected = [] if case.seeded else ["INSERT INTO projects"]  # a seeded job has its project
    expected += ["HTTP", USAGE_INSERT, *own]
    assert trace == expected
    assert await w.count("usage_events") == 1


@pytest.mark.parametrize("case", WITH_OWN_WRITE, ids=ids(WITH_OWN_WRITE))
async def test_a_failing_own_write_keeps_the_event(research_world, case):
    w = await build(research_world, case)
    fail_statements(w, case.own_write)
    await w.call(case.tool, **case.arguments)  # a warning result or an error: either way
    assert await w.count("usage_events") == 1  # the spend was recorded before the write failed
    if case.tool == "perplexity_chat":
        assert await w.count("chats") == 0 and await w.count("chat_messages") == 0
    elif case.tool == "perplexity_research":
        assert await w.count("research_jobs") == 0
    else:
        stored = await job(w)
        assert stored["status"] == "in_progress" and stored["usage_recorded"] == 0


CLOCK_FIELDS = {"latency_ms", "created_at", "updated_at"}  # wall-clock values, never equal


def stable(result) -> dict[str, Any]:
    """The structured result without the fields that carry a wall-clock reading."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in CLOCK_FIELDS}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return clean(result.structured_content)


class ReleaseOnLostEvent(logging.Handler):
    """Releases the held lock the moment the recorder gives up, so the tool's own write that
    follows is not also locked out (the test is about the recorder alone)."""

    def __init__(self, lock: DbLock) -> None:
        super().__init__(logging.WARNING)
        self.held = lock
        self.fired = 0

    def emit(self, record: logging.LogRecord) -> None:
        if "usage event not recorded" in record.getMessage():
            self.fired += 1
            self.held.release()


@pytest.mark.parametrize("case", CASES, ids=ids(CASES))
async def test_a_database_locked_past_the_busy_timeout_leaves_the_result_unchanged(
    research_world, tmp_path, case
):
    baseline = await build(research_world, case, data_dir=tmp_path / "baseline")
    expected = await baseline.call(case.tool, **case.arguments)
    assert not expected.is_error and await baseline.count("usage_events") == 1

    w = await build(research_world, case, data_dir=tmp_path / "locked", db_busy_timeout=BUSY)
    lock = DbLock(database_path(w.settings.data_dir))
    handler = ReleaseOnLostEvent(lock)
    logger = logging.getLogger("mcp_perplexity_pro.usage")
    logger.addHandler(handler)
    inner = w.upstream.responder
    w.upstream.responder = lambda request, n: (lock.acquire(), inner(request, n))[1]
    try:
        locked = await w.call(case.tool, **case.arguments)
    finally:
        logger.removeHandler(handler)
        lock.close()
    assert handler.fired == 1  # the lock really cost the event ...
    assert await w.count("usage_events") == 0
    assert not locked.is_error and stable(locked) == stable(expected)  # ... and nothing else

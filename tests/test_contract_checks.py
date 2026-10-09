"""Task 5.3: contract checks across the seven tools.

1. ``record_usage`` has exactly the call sites design D4 names (a mechanical sweep).
2. Every anticipated failure the specs name surfaces as its listed category through the real
   middleware, and never as ``internal_error``.
3. The configured API key appears in no result, log record or stored row after a run of all
   four tools with a key-echoing upstream; key-shaped tokens appear only inside the content
   fields design D14 carves out; every upstream-originated string is redacted and capped.
"""

import ast
import json
import sqlite3
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2
import pytest
from agent_support import World, fixture, inline, respond_with
from chat_support import FIRST, seed_chat
from research_support import COMPLETED, IN_PROGRESS, RUN_ID, Clock, routes, seed_job, serve
from secrets_support import (
    ASK,
    CHAT,
    CONTENT_COLUMNS,
    CONTENT_RESULT_PATHS,
    JOBS,
    KEY,
    KEY_FREE,
    OTHER,
    QUEUED,
    RESEARCH,
    SHAPED,
    completed_body,
    error_body,
    ok,
    walk,
)
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from usage_support import DbLock

from mcp_perplexity_pro.storage.engine import database_path

SRC = Path(__file__).resolve().parent.parent / "src" / "mcp_perplexity_pro"


# --- 1. the recorder has exactly the call sites design D4 names -------------------------------


def record_usage_calls() -> Counter:
    """``(file, enclosing function)`` of every call to ``record_usage`` under ``src/``."""
    found: Counter = Counter()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and getattr(inner.func, "id", None) == "record_usage"
                ):
                    found[(path.relative_to(SRC).as_posix(), node.name)] += 1
    return found


def test_record_usage_is_called_from_exactly_two_functions_and_defined_once():
    calls = record_usage_calls()
    # run_costed records a failure and a response (two calls in one function); observe_job
    # records a finished run. Nothing else, in any tool module, calls the recorder.
    assert calls == Counter({("agent.py", "run_costed"): 2, ("agent.py", "observe_job"): 1})
    definitions = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if any(
            isinstance(n, ast.AsyncFunctionDef) and n.name == "record_usage"
            for n in ast.walk(ast.parse(path.read_text()))
        )
    ]
    assert definitions == ["usage.py"]
    for tool in (SRC / "tools").glob("*.py"):  # the tools reach it only through those two
        assert "record_usage" not in tool.read_text(), tool.name


# --- 2. the category table --------------------------------------------------------------------

LONG = "x" * 20001


def raising(exc_factory: Callable[[httpx2.Request], Exception]):
    def responder(request, n):
        raise exc_factory(request)

    return responder


async def chat_one(w: World) -> None:
    await seed_chat(w, "default", "Teal", 2)


async def chat_in_project_a(w: World) -> None:
    await seed_chat(w, "a", "Teal", 2)


async def job_one(w: World) -> None:
    await seed_job(w, response_id=RUN_ID)


@dataclass(frozen=True)
class Row:
    """One scenario of a spec that names a category."""

    scenario: str  # the spec scenario, for the failure message
    tool: str
    arguments: dict[str, Any]
    expected: str
    responder: Any = None  # None: the plain fast ask response
    setup: Callable[[World], Awaitable[None]] | None = None
    settings: dict[str, Any] = field(default_factory=dict)


SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}
RUNNING = routes(get=[IN_PROGRESS])
BAD_400 = "agent_chat_bad_previous_response_400.json"

ROWS = [
    # --- agent-ask: local validation (nothing is sent) ---
    Row("ask: blank query", ASK, {"query": "   "}, "invalid_request"),
    Row("ask: oversized query", ASK, {"query": LONG}, "invalid_request"),
    Row("ask: depth high", ASK, {"query": "q", "depth": "high"}, "invalid_request"),
    Row(
        "ask: depth with a model",
        ASK,
        {"query": "q", "depth": "low", "model": "openai/gpt-6-luna"},
        "invalid_request",
    ),
    Row(
        "ask: search false without a model", ASK, {"query": "q", "search": False}, "invalid_request"
    ),
    Row(
        "ask: mixed domain list",
        ASK,
        {"query": "q", "domains": ["python.org", "-reddit.com"]},
        "invalid_request",
    ),
    Row(
        "ask: 21 domains",
        ASK,
        {"query": "q", "domains": [f"d{i}.com" for i in range(21)]},
        "invalid_request",
    ),
    Row("ask: empty domain", ASK, {"query": "q", "domains": [""]}, "invalid_request"),
    Row("ask: malformed date", ASK, {"query": "q", "after": "09/15/2026"}, "invalid_request"),
    Row(
        "ask: dates out of order",
        ASK,
        {"query": "q", "after": "2026-10-01", "before": "2026-09-01"},
        "invalid_request",
    ),
    Row("ask: bad recency", ASK, {"query": "q", "recency": "fortnight"}, "invalid_request"),
    Row("ask: max_results 0", ASK, {"query": "q", "max_results": 0}, "invalid_request"),
    Row(
        "ask: filter with search false",
        ASK,
        {"query": "q", "model": "openai/gpt-6-luna", "search": False, "recency": "week"},
        "invalid_request",
    ),
    Row(
        "ask: output cap out of bounds",
        ASK,
        {"query": "q", "max_output_tokens": 64001},
        "invalid_request",
    ),
    Row(
        "ask: instructions too long",
        ASK,
        {"query": "q", "instructions": "i" * 10001},
        "invalid_request",
    ),
    Row(
        "ask: schema root not an object",
        ASK,
        {"query": "q", "json_schema": {"type": "array"}},
        "invalid_request",
    ),
    Row("ask: invalid project name", ASK, {"query": "q", "project": "../etc"}, "invalid_request"),
    Row("ask: wrong argument type", ASK, {"query": 5}, "invalid_request"),
    # --- agent-ask: the API answers ---
    Row(
        "ask: the generic 400 for an inner schema",
        ASK,
        {"query": "q", "json_schema": SCHEMA},
        "invalid_request",
        respond_with("agent_structured_bad_inner_400.json", 400),
    ),
    Row(
        "ask: a recorded 400 body",
        ASK,
        {"query": "q"},
        "invalid_request",
        respond_with("agent_bad_recency_400.json", 400),
    ),
    Row("ask: 401", ASK, {"query": "q"}, "authentication", error_body(401, "bad key", "auth")),
    Row("ask: 403", ASK, {"query": "q"}, "forbidden", error_body(403, "no access", "forbidden")),
    Row("ask: 404", ASK, {"query": "q"}, "not_found", error_body(404, "gone", "not_found")),
    Row(
        "ask: 429 beyond the maximum wait",
        ASK,
        {"query": "q"},
        "rate_limited",
        error_body(429, "slow down", "rate_limit", **{"Retry-After": "9999"}),
    ),
    Row("ask: 503", ASK, {"query": "q"}, "upstream_failure", error_body(503, "down", "server")),
    Row(
        "ask: read timeout",
        ASK,
        {"query": "q"},
        "network_timeout",
        raising(lambda request: httpx2.ReadTimeout("cut", request=request)),
    ),
    Row(
        "ask: a failed run on HTTP 200",
        ASK,
        {"query": "q"},
        "unexpected_response",
        lambda request, n: httpx2.Response(
            200, json=inline("failed", error={"message": "boom", "type": "x", "code": "e"})
        ),
    ),
    Row(
        "ask: completed with an error",
        ASK,
        {"query": "q"},
        "unexpected_response",
        lambda request, n: httpx2.Response(
            200, json=inline("completed", error={"message": "boom"})
        ),
    ),
    Row(
        "ask: still in progress",
        ASK,
        {"query": "q"},
        "unexpected_response",
        lambda request, n: httpx2.Response(200, json=inline("in_progress")),
    ),
    Row(
        "client: a create response without a status",
        ASK,
        {"query": "q"},
        "unexpected_response",
        lambda request, n: httpx2.Response(200, json={"id": "resp_x", "output": []}),
    ),
    Row(
        "client: a body that is not JSON",
        ASK,
        {"query": "q"},
        "unexpected_response",
        lambda request, n: httpx2.Response(200, text="<html>gateway</html>"),
    ),
    # --- agent-chat ---
    Row("chat: unknown action", CHAT, {"action": "rename"}, "invalid_request"),
    Row("chat: no title", CHAT, {"action": "send", "message": FIRST}, "invalid_request"),
    Row(
        "chat: blank title",
        CHAT,
        {"action": "send", "message": FIRST, "title": "   "},
        "invalid_request",
    ),
    Row(
        "chat: title of 121",
        CHAT,
        {"action": "send", "message": FIRST, "title": "t" * 121},
        "invalid_request",
    ),
    Row(
        "chat: blank message",
        CHAT,
        {"action": "send", "message": "   ", "title": "T"},
        "invalid_request",
    ),
    Row(
        "chat: oversized message",
        CHAT,
        {"action": "send", "message": LONG, "title": "T"},
        "invalid_request",
    ),
    Row(
        "chat: blank message with a chat id",
        CHAT,
        {"action": "send", "message": "  ", "chat_id": 1},
        "invalid_request",
        setup=chat_one,
    ),
    Row(
        "chat: title with a chat id",
        CHAT,
        {"action": "send", "message": FIRST, "chat_id": 1, "title": "T"},
        "invalid_request",
        setup=chat_one,
    ),
    Row(
        "chat: replay without a chat",
        CHAT,
        {"action": "send", "message": FIRST, "title": "T", "replay": True},
        "invalid_request",
    ),
    Row(
        "chat: json_schema is refused",
        CHAT,
        {"action": "send", "message": FIRST, "title": "T", "json_schema": SCHEMA},
        "invalid_request",
    ),
    Row(
        "chat: unknown chat",
        CHAT,
        {"action": "send", "message": FIRST, "chat_id": 999},
        "not_found",
        setup=chat_one,
    ),
    Row(
        "chat: a chat of another project",
        CHAT,
        {"action": "send", "message": FIRST, "chat_id": 1, "project": "b"},
        "not_found",
        setup=chat_in_project_a,
    ),
    Row(
        "chat: send in an absent project",
        CHAT,
        {"action": "send", "message": FIRST, "chat_id": 1, "project": "ghost"},
        "not_found",
    ),
    Row(
        "chat: read in an absent project",
        CHAT,
        {"action": "read", "chat_id": 1, "project": "ghost"},
        "not_found",
    ),
    Row(
        "chat: delete in an absent project",
        CHAT,
        {"action": "delete", "chat_id": 1, "project": "ghost", "confirm": True},
        "not_found",
    ),
    Row(
        "chat: read an unknown chat",
        CHAT,
        {"action": "read", "chat_id": 999},
        "not_found",
        setup=chat_one,
    ),
    Row("chat: read without a chat id", CHAT, {"action": "read"}, "invalid_request"),
    Row(
        "chat: delete without a chat id",
        CHAT,
        {"action": "delete", "confirm": True},
        "invalid_request",
    ),
    Row("chat: a bad list limit", CHAT, {"action": "list", "limit": 0}, "invalid_request"),
    Row(
        "chat: delete without confirm",
        CHAT,
        {"action": "delete", "chat_id": 1},
        "confirmation_required",
        setup=chat_one,
    ),
    Row(
        "chat: the generic 400 on a chained send",
        CHAT,
        {"action": "send", "message": FIRST, "chat_id": 1},
        "invalid_request",
        respond_with(BAD_400, 400),
        setup=chat_one,
    ),
    Row(
        "chat: a failed run on HTTP 200",
        CHAT,
        {"action": "send", "message": FIRST, "title": "T"},
        "unexpected_response",
        lambda request, n: httpx2.Response(200, json=inline("failed", error={"message": "boom"})),
    ),
    Row(
        "chat: a locked database at delete",
        CHAT,
        {"action": "delete", "chat_id": 1, "confirm": True},
        "storage_busy",
        setup=chat_one,
        settings={"db_busy_timeout": 0.2},
    ),
    # --- agent-research ---
    Row("research: blank query", RESEARCH, {"query": " "}, "invalid_request"),
    Row("research: depth fast", RESEARCH, {"query": "q", "depth": "fast"}, "invalid_request"),
    Row(
        "research: instructions too long",
        RESEARCH,
        {"query": "q", "instructions": "i" * 10001},
        "invalid_request",
    ),
    Row(
        "research: a 429 beyond the maximum wait",
        RESEARCH,
        {"query": "q"},
        "rate_limited",
        error_body(429, "slow down", "rate_limit", **{"Retry-After": "9999"}),
    ),
    Row(
        "research: a malformed response id",
        RESEARCH,
        {"query": "q"},
        "unexpected_response",
        lambda request, n: httpx2.Response(200, json=inline("queued") | {"id": "x/../y"}),
    ),
    Row(
        "research: a 503 submit",
        RESEARCH,
        {"query": "q"},
        "upstream_failure",
        error_body(503, "down", "server"),
    ),
    # --- agent-research: jobs ---
    Row("jobs: unknown action", JOBS, {"action": "purge"}, "invalid_request"),
    Row("jobs: status without a job id", JOBS, {"action": "status"}, "invalid_request"),
    Row("jobs: result without a job id", JOBS, {"action": "result"}, "invalid_request"),
    Row("jobs: cancel without a job id", JOBS, {"action": "cancel"}, "invalid_request"),
    Row("jobs: a bad list limit", JOBS, {"action": "list", "limit": 0}, "invalid_request"),
    Row(
        "jobs: an unknown job",
        JOBS,
        {"action": "status", "job_id": 999},
        "not_found",
        setup=job_one,
    ),
    Row(
        "jobs: result of an unknown job",
        JOBS,
        {"action": "result", "job_id": 999},
        "not_found",
        setup=job_one,
    ),
    Row(
        "jobs: cancel of an unknown job",
        JOBS,
        {"action": "cancel", "job_id": 999},
        "not_found",
        setup=job_one,
    ),
    Row(
        "jobs: another project's job",
        JOBS,
        {"action": "status", "job_id": 1, "project": "b"},
        "not_found",
        setup=job_one,
    ),
    Row(
        "jobs: status in an absent project",
        JOBS,
        {"action": "status", "job_id": 1, "project": "ghost"},
        "not_found",
    ),
    Row(
        "jobs: a failing fetch",
        JOBS,
        {"action": "status", "job_id": 1},
        "upstream_failure",
        error_body(503, "down", "server"),
        setup=job_one,
    ),
    Row(
        "jobs: a cancel refused for another reason",
        JOBS,
        {"action": "cancel", "job_id": 1},
        "invalid_request",
        routes(
            get=[IN_PROGRESS],
            cancel=[
                serve(
                    {"error": {"message": "cancel is not allowed here", "type": "x", "code": 400}},
                    400,
                )
            ],
        ),
        setup=job_one,
    ),
]


def vet_updates_as_busy(w: World) -> None:
    """Fail every UPDATE of ``research_jobs`` as a locked database does at the driver."""

    @event.listens_for(w.engine.sync_engine, "before_cursor_execute")
    def boom(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE RESEARCH_JOBS"):
            raise OperationalError(
                statement, parameters, sqlite3.OperationalError("database is locked")
            )


@pytest.mark.parametrize("row", ROWS, ids=[r.scenario for r in ROWS])
async def test_every_anticipated_failure_surfaces_as_its_listed_category(research_world, row):
    w = await research_world(row.responder or respond_with(KEY_FREE), **row.settings)
    if row.setup:
        await row.setup(w)
    lock = None
    if row.expected == "storage_busy":  # hold the write lock past the busy timeout
        lock = DbLock(database_path(w.settings.data_dir))
        lock.acquire()
    try:
        result = await w.call(row.tool, **row.arguments)
    finally:
        if lock:
            lock.close()
    assert result.is_error, f"{row.scenario}: expected an error, got {result.structured_content}"
    got = result.structured_content["category"]
    assert got != "internal_error", f"{row.scenario}: {result.structured_content}"
    assert got == row.expected, row.scenario
    assert result.content[0].text.startswith(f"[{row.expected}] ")


async def test_a_busy_database_during_a_job_observation_is_storage_busy(research_world):
    w = await research_world(routes(get=[COMPLETED]), clock=Clock())
    await seed_job(w, response_id=RUN_ID)
    vet_updates_as_busy(w)
    result = await w.call(JOBS, action="status", job_id=1)
    assert result.is_error and result.structured_content["category"] == "storage_busy"
    assert await w.count("usage_events") == 1  # the spend was recorded before the update failed


async def test_a_busy_database_at_the_research_row_insert_is_storage_busy(research_world):
    w = await research_world(routes(post=["agent_background_submit_medium.json"]))

    @event.listens_for(w.engine.sync_engine, "before_cursor_execute")
    def boom(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO RESEARCH_JOBS"):
            raise OperationalError(
                statement, parameters, sqlite3.OperationalError("database is locked")
            )

    result = await w.call(RESEARCH, query="q")
    assert result.is_error and result.structured_content["category"] == "storage_busy"
    assert RUN_ID in result.structured_content["message"]  # the id to cancel by hand


# --- 3. secrets: the configured key, key-shaped tokens and upstream text ----------------------


def echo_401():
    return error_body(401, f"Invalid API key {KEY} (also saw {OTHER})", "invalid_api_key")


async def test_the_configured_key_and_key_shapes_appear_nowhere_after_all_four_tools_ran(keyed):
    run = await keyed()
    failed_with_echo = inline(
        "failed",
        error={"message": f"upstream said {KEY} and {OTHER}", "type": KEY, "code": KEY},
    )
    cut_short = completed_body("partial", title="t", url="https://example.com/a", rid="resp_inc")
    cut_short.update(
        status="incomplete",
        model=f"openai/{KEY}",
        incomplete_details={"reason": f"stopped near {KEY} and {OTHER}"},
    )
    submit = fixture(QUEUED)
    submit["status"] = f"paused-{KEY}"
    snapshot = fixture(COMPLETED)
    snapshot.update(
        status="failed",
        model=f"openai/{KEY}",
        error={"message": f"run died: {KEY} {OTHER}", "type": "x", "code": "e"},
    )

    # an upstream that echoes the key in its error body, for each of the four tools
    await run(ASK, echo_401(), query="q")
    await run(CHAT, action="send", message=FIRST, title="Teal")
    await run(RESEARCH, query="q")
    # a submit whose status echoes the key is stored as a running job, redacted
    await run(RESEARCH, ok(submit), query="q")
    await run(JOBS, echo_401(), action="status", job_id=1)
    # 200 bodies that echo the key in the strings the API originates
    await run(ASK, ok(failed_with_echo), query="q")
    await run(ASK, ok(cut_short), query="q")
    await run(CHAT, ok(cut_short), action="send", message=FIRST, title="Teal")
    await run(
        CHAT,
        ok(
            completed_body(
                "fine", title="t", url="https://e.com/", rid="resp_c", model=f"openai/{KEY}"
            )
        ),
        action="send",
        message=FIRST,
        title="Teal",
    )
    await run(JOBS, ok(snapshot), action="status", job_id=1)
    await run(JOBS, action="result", job_id=1)
    await run(JOBS, action="list", refresh=True)
    await run(CHAT, action="list")
    await run(CHAT, action="read", chat_id=1)
    assert any(r.is_error for r in run.results) and any(not r.is_error for r in run.results)
    assert {r.structured_content.get("category") for r in run.results if r.is_error} >= {
        "authentication",
        "unexpected_response",
    }

    for text in run.texts():
        assert KEY not in text and not SHAPED.search(text), text[:300]
    log = run.log_text()
    assert KEY not in log and not SHAPED.search(log)
    for table, column, value in await run.cells():
        assert KEY not in value and not SHAPED.search(value), (table, column)
    data = run.database_bytes()
    assert KEY.encode() not in data and b"pplx-Zy9_" not in data
    # the strings were stored, redacted, not dropped
    (stored,) = await run.w.rows("SELECT status, model, error_text FROM research_jobs")
    assert stored[0] == "failed" and "[redacted]" in stored[1] and "[redacted]" in stored[2]


async def test_key_shaped_content_is_returned_and_stored_unchanged_and_nowhere_else(keyed):
    run = await keyed()
    ask_answer = f"Use the example {OTHER} as the placeholder."
    ask_title, ask_url = f"About {OTHER}", f"https://example.com/{OTHER}"
    chat_answer = f"The token looks like {OTHER}."
    job_answer = f"Research says {OTHER}."
    snapshot = fixture(COMPLETED)
    for item in snapshot["output"]:
        if item["type"] == "message":
            item["content"][-1]["text"] = job_answer
        if item["type"] == "search_results":
            item["results"][0]["title"] = f"Doc {OTHER}"
            item["results"][0]["url"] = f"https://example.com/{OTHER}/doc"
    seeded = [ask_answer, ask_title, ask_url, chat_answer, job_answer, f"Doc {OTHER}"]

    ask = await run(
        ASK,
        ok(completed_body(ask_answer, title=ask_title, url=ask_url, rid="resp_ask")),
        query=f"What is {OTHER}?",
        instructions=f"Never print {OTHER}.",
    )
    sent = await run(
        CHAT,
        ok(completed_body(chat_answer, title="t", url="https://e.com/", rid="resp_chat")),
        action="send",
        message=f"Is {OTHER} valid?",
        title=f"Notes on {OTHER}",
    )
    await run(RESEARCH, ok(fixture(QUEUED)), query=f"Find {OTHER}", instructions=f"Not {OTHER}")
    await run(JOBS, ok(snapshot), action="status", job_id=1)
    done = await run(JOBS, action="result", job_id=1)
    await run(JOBS, action="list")
    read = await run(CHAT, action="read", chat_id=1)
    await run(CHAT, action="list")
    # an API error that echoes the example is server-originated text: redacted, not content
    refused = await run(ASK, error_body(400, f"bad input {OTHER}"), query=f"What is {OTHER}?")

    # returned as given
    assert ask.structured_content["answer"] == ask_answer
    assert ask.structured_content["sources"][0]["title"] == ask_title
    assert ask.structured_content["sources"][0]["url"] == ask_url
    assert sent.structured_content["answer"] == chat_answer
    assert [m["content"] for m in read.structured_content["messages"]] == [
        f"Is {OTHER} valid?",
        chat_answer,
    ]
    assert read.structured_content["chat"]["title"] == f"Notes on {OTHER}"
    assert done.structured_content["answer"] == job_answer
    # stored as given
    assert await run.w.rows("SELECT title FROM chats") == [(f"Notes on {OTHER}",)]
    assert (await run.w.rows("SELECT query FROM research_jobs")) == [(f"Find {OTHER}",)]
    assert (await run.w.rows("SELECT result_text FROM research_jobs")) == [(job_answer,)]

    # and an error carrying the example has it removed
    assert refused.is_error and OTHER not in refused.structured_content["message"]

    # a key-shaped token appears only inside the carved-out content fields
    for result in run.results:
        for path, value in walk(result.structured_content):
            if SHAPED.search(value):
                assert path in CONTENT_RESULT_PATHS, (path, value[:80])
        for part in result.content:  # the readable rendering: content strings, nothing else
            leftover = part.text
            for content in [*seeded, f"Is {OTHER} valid?", f"Notes on {OTHER}", f"Find {OTHER}"]:
                leftover = leftover.replace(content, "")
            assert not SHAPED.search(leftover), part.text[:300]
    for table, column, value in await run.cells():
        if SHAPED.search(value):
            assert (table, column) in CONTENT_COLUMNS, (table, column, value[:80])
    # the configured key is not among them, and no log record carries any key-shaped token
    log = run.log_text()
    assert len(log) > 1000  # the DEBUG run really logged
    assert KEY not in log and not SHAPED.search(log)
    assert KEY.encode() not in run.database_bytes()


async def test_health_carries_no_key_and_no_content(keyed):
    run = await keyed()
    await run(ASK, query=f"What is {OTHER}?")
    app = run.w.server.http_app()
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://t"
    ) as c:
        health = await c.get("/health")
    assert health.status_code == 200
    assert KEY not in health.text and not SHAPED.search(health.text)


# --- upstream-originated strings: redacted, then cut ------------------------------------------

FILL = "x"


def padded(head: int, secret: str, tail: int) -> str:
    return FILL * head + secret + FILL * tail


def stored(w: World, column: str, table: str = "research_jobs"):
    return w.rows(f"SELECT {column} FROM {table} ORDER BY id")


async def test_every_upstream_string_is_redacted_then_cut_to_its_cap(keyed):
    run = await keyed()
    w = run.w
    # the key straddles each cut: 60 characters then the key, so a cut after redaction lands in
    # the middle of "[redacted]" and a cut before redaction would leave a key fragment
    status_64 = padded(60, KEY, 100)
    reason_200 = padded(196, KEY, 100)
    error_2000 = padded(1996, KEY, 100)

    # ask: an odd status is named in the error, a reason in the result and its warning
    refused = await run(ASK, ok(inline(status_64)), query="q")
    cut = completed_body("partial", title="t", url="https://e.com/", rid="resp_inc")
    cut.update(status="incomplete", incomplete_details={"reason": reason_200})
    reasoned = await run(ASK, ok(cut), query="q")
    broken = await run(
        ASK,
        ok(inline("failed", error={"message": error_2000, "type": "x", "code": "e"})),
        query="q",
    )
    message = refused.structured_content["message"]
    assert "pplx-" not in message and FILL * 65 not in message
    assert "[red" in message  # the status was cut inside the placeholder, not before it
    reason = reasoned.structured_content["incomplete_reason"]
    assert "pplx-" not in reason and len(reason) <= 200 and reason.startswith(FILL * 196)
    assert all("pplx-" not in x for x in reasoned.structured_content["warnings"])
    detail = broken.structured_content["message"]
    assert "pplx-" not in detail and len(detail) < 2300 and FILL * 2001 not in detail

    # research: a submit with an odd status is stored verbatim (redacted, cut to 64)
    submit = fixture(QUEUED)
    submit["status"] = status_64
    started = await run(RESEARCH, ok(submit), query="q")
    assert started.structured_content["status"] == (
        stored_status := (await stored(w, "status"))[0][0]
    )
    assert len(stored_status) <= 64 and "pplx-" not in stored_status
    # jobs: a polled odd status, a failed run's error text and an incomplete run's reason
    odd = fixture(QUEUED)
    odd["status"] = status_64
    polled = await run(JOBS, ok(odd), action="status", job_id=1)
    assert len(polled.structured_content["status"]) <= 64
    assert "pplx-" not in json.dumps(polled.structured_content)

    failed = fixture(COMPLETED)
    failed.update(status="failed", error={"message": error_2000, "type": "x", "code": "e"})
    await run(RESEARCH, ok(fixture(QUEUED) | {"id": "resp_second"}), query="second")
    await run(JOBS, ok(failed), action="status", job_id=2)
    incomplete = fixture(COMPLETED)
    incomplete.update(status="incomplete", incomplete_details={"reason": reason_200})
    await run(RESEARCH, ok(fixture(QUEUED) | {"id": "resp_third"}), query="third")
    await run(JOBS, ok(incomplete), action="status", job_id=3)

    ((_, error_text),) = await w.rows("SELECT id, error_text FROM research_jobs WHERE id = 2")
    ((_, kept_reason),) = await w.rows(
        "SELECT id, incomplete_reason FROM research_jobs WHERE id = 3"
    )
    assert error_text and len(error_text) <= 2000 and "pplx-" not in error_text
    assert error_text.startswith(FILL * 1996) and "[red" in error_text
    assert kept_reason and len(kept_reason) <= 200 and "pplx-" not in kept_reason
    for (status,) in await stored(w, "status"):
        assert len(status) <= 64 and "pplx-" not in status
    # nothing anywhere carries the key, a key shape or a fragment of the key
    for text in run.texts():
        assert "pplx-" not in text and "Zy9_Zy9_" not in text
    for table, column, value in await run.cells():
        if (table, column) not in CONTENT_COLUMNS:
            assert "pplx-" not in value and "Zy9_Zy9_" not in value, (table, column)
    assert "Zy9_Zy9_" not in run.log_text()


async def test_the_seven_tools_are_listed_and_each_has_an_output_schema(research_world):
    """The tool surface whose ``tools/list`` size design.md Risks records (3 tools before)."""
    from fastmcp import Client

    w = await research_world()
    async with Client(w.server) as client:
        tools = await client.list_tools()
    assert sorted(t.name for t in tools) == [
        "perplexity_ask",
        "perplexity_chat",
        "perplexity_jobs",
        "perplexity_models",
        "perplexity_projects",
        "perplexity_research",
        "perplexity_usage",
    ]
    assert all(t.output_schema for t in tools)

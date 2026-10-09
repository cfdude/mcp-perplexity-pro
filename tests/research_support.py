"""Helpers for the research and jobs tool tests: a world builder with an injectable clock, a
scripted responder, and direct reads and seeds of ``research_jobs``."""

import json
from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from agent_support import World, fixture, make_world

SUBMIT = "agent_background_submit_medium.json"
IN_PROGRESS = "agent_background_in_progress.json"
COMPLETED = "agent_background_completed.json"
CANCELLED = "agent_background_cancelled.json"
CANCEL_ACCEPTED = "agent_cancel_accepted.json"
CANCEL_TERMINAL_400 = "agent_cancel_terminal_400.json"
GET_404 = "agent_get_unknown_404.json"
RUN_ID = fixture(SUBMIT)["id"]  # the id of the queued, in-progress and completed captures
CANCELLED_ID = fixture(CANCELLED)["id"]
T0 = datetime(2026, 10, 9, 12, 0, 0)  # the injected clock's start (naive UTC)


class Clock:
    """An injectable ``now`` (naive UTC) that only moves when a test moves it."""

    def __init__(self, start: datetime = T0) -> None:
        self.value = start

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **delta: float) -> None:
        self.value += timedelta(**delta)


def serve(name_or_body: Any, status: int = 200, **headers: str):
    """A response for ``responder`` entries: a fixture name or a body."""
    body = fixture(name_or_body) if isinstance(name_or_body, str) else name_or_body
    return httpx2.Response(status, json=body, headers=headers)


def routes(**table: Any):
    """A responder that picks by method and path suffix, from a script of lists.

    ``routes(get=[...], post=[...], cancel=[...])``: each list holds entries (a fixture name, a
    body, ``(name, status)`` or a ready response) consumed in order, the last one repeating. A
    ``get`` serves ``GET /v1/agent/{id}``, a ``post`` serves ``POST /v1/agent`` and a ``cancel``
    serves ``POST /v1/agent/{id}/cancel``.
    """
    used = {key: 0 for key in table}

    def responder(request, n):
        path = request.url.path
        if request.method == "GET":
            key = "get"
        elif path.endswith("/cancel"):
            key = "cancel"
        else:
            key = "post"
        entries = table[key]
        entry = entries[min(used[key], len(entries) - 1)]
        used[key] += 1
        if isinstance(entry, httpx2.Response):
            return entry
        if isinstance(entry, tuple):
            return serve(entry[0], entry[1])
        return serve(entry)

    return responder


def request_log(w: World) -> list[str]:
    """``METHOD path`` of every request the upstream received, in order."""
    return [f"{r.method} {r.url.path}" for r in w.requests]


@pytest.fixture
async def research_world(make_settings):
    made: list[World] = []

    async def build(responder=None, *, clock: Clock | None = None, **settings):
        w = await make_world(
            make_settings,
            responder or routes(post=[SUBMIT]),
            now=clock or Clock(),
            **settings,
        )
        made.append(w)
        return w

    yield build
    for w in made:
        await w.aclose()


JOB_COLUMNS = (
    "id, project_id, query, depth, response_id, status, model, started_at, last_checked_at, "
    "finished_at, cancel_requested_at, missing_since, result_text, sources_json, "
    "incomplete_reason, error_text, input_tokens, output_tokens, total_tokens, cost_nano_usd, "
    "cost_source, usage_recorded"
)


async def job_rows(w: World) -> list[dict[str, Any]]:
    rows = await w.rows(f"SELECT {JOB_COLUMNS} FROM research_jobs ORDER BY id")
    names = [c.strip() for c in JOB_COLUMNS.split(",")]
    return [dict(zip(names, row, strict=True)) for row in rows]


async def job(w: World, job_id: int = 1) -> dict[str, Any]:
    (row,) = [r for r in await job_rows(w) if r["id"] == job_id]
    return row


async def seed_job(
    w: World,
    *,
    project: str = "default",
    response_id: str = RUN_ID,
    status: str = "in_progress",
    depth: str = "medium",
    query: str = "a research question",
    started_at: datetime = T0,
    **columns: Any,
) -> int:
    """A job row written straight to storage (no upstream call, no usage event)."""
    from mcp_perplexity_pro.storage.jobs import insert_job
    from mcp_perplexity_pro.storage.projects import get_or_create_project
    from mcp_perplexity_pro.storage.session import unit_of_work

    async with unit_of_work(w.engine) as session:
        pid = (await get_or_create_project(session, project)).id
        row = await insert_job(
            session,
            pid,
            {
                "query": query,
                "depth": depth,
                "response_id": response_id,
                "status": status,
                "started_at": started_at,
                **columns,
            },
        )
    return row.id


def parsed(result) -> dict[str, Any]:
    return json.loads(json.dumps(result.structured_content))

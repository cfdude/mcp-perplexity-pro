"""Shared pieces of the secrets and contract checks (task 5.3 and its content-scrub fix): the
configured key and a key-shaped example, a world whose configured key is that key, a run
recorder that keeps every result, the log and the database for inspection, and the carve-out
tables of design D14.

Do not use ``from __future__ import annotations`` here: FastMCP reads annotations at
registration time (nothing registered here, but the rule of this suite holds)."""

import json
import logging
import re
from typing import Any

import httpx2
import pytest
from agent_support import World, fixture, respond_with
from research_support import Clock

from mcp_perplexity_pro.log_setup import configure_logging
from mcp_perplexity_pro.storage.engine import database_path

KEY_FREE = "agent_fast.json"


def error_body(status: int, message: str, kind: str = "invalid_request", **headers: str):
    body = {"error": {"message": message, "type": kind, "code": status}}
    return lambda request, n: httpx2.Response(status, json=body, headers=headers)


ASK = "perplexity_ask"
CHAT = "perplexity_chat"
RESEARCH = "perplexity_research"
JOBS = "perplexity_jobs"
KEY = "pplx-" + "Zy9_" * 8  # the configured key (key-shaped, so the shape rule also sees it)
OTHER = "pplx-" + "Qq7-" * 8  # a key-shaped example that is NOT the configured key
SHAPED = re.compile(r"pplx-[A-Za-z0-9_-]{8,}")  # independent of the implementation's pattern
QUEUED = "agent_background_submit_medium.json"


def completed_body(answer: str, *, title: str, url: str, rid: str, model: str | None = None):
    """A completed fast response with a chosen answer and one search result."""
    body = fixture("agent_fast.json")
    body["id"] = rid
    if model is not None:
        body["model"] = model
    body["output"] = [
        {
            "type": "search_results",
            "queries": ["q"],
            "results": [
                {"id": 1, "url": url, "title": title, "snippet": "s", "date": "2026-10-01"}
            ],
        },
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": answer, "annotations": []}],
        },
    ]
    return body


def ok(body: Any, status: int = 200):
    return lambda request, n: httpx2.Response(status, json=body)


class Run:
    """Calls tools on one world, keeping every result and the log of the whole run.

    Logging is configured the way the server configures it (``configure_logging``: stderr through
    the redacting filter, at DEBUG so third-party debug lines are in play too), and the records of
    this server's own loggers are also kept raw, before any filter."""

    def __init__(self, w: World, caplog, capsys) -> None:
        self.w, self.caplog, self.capsys, self.results = w, caplog, capsys, []
        caplog.set_level(logging.DEBUG)
        configure_logging("DEBUG", [KEY])

    async def __call__(self, tool: str, responder=None, **arguments: Any):
        if responder is not None:
            self.w.upstream.responder = responder
        result = await self.w.call(tool, **arguments)
        self.results.append(result)
        return result

    def texts(self) -> list[str]:
        """Every string a client received: the structured content as JSON and each text part."""
        out = []
        for result in self.results:
            out.append(json.dumps(result.structured_content))
            out.extend(c.text for c in result.content)
        return out

    def log_text(self) -> str:
        """What the server wrote to stderr, plus this server's own records as raw."""
        fmt = logging.Formatter()
        own = [r for r in self.caplog.records if r.name.startswith("mcp_perplexity_pro")]
        return self.capsys.readouterr().err + "\n" + "\n".join(fmt.format(r) for r in own)

    async def cells(self) -> list[tuple[str, str, str]]:
        """``(table, column, value)`` of every cell of every table in the database."""
        out = []
        tables = [
            r[0]
            for r in await self.w.rows(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            columns = [r[1] for r in await self.w.rows(f"PRAGMA table_info({table})")]
            for row in await self.w.rows(f"SELECT * FROM {table}"):
                out.extend((table, c, str(v)) for c, v in zip(columns, row, strict=True))
        return out

    def database_bytes(self) -> bytes:
        base = database_path(self.w.settings.data_dir)
        return b"".join(p.read_bytes() for p in base.parent.glob(base.name + "*") if p.is_file())


@pytest.fixture
async def keyed(research_world, caplog, capsys):
    """A world whose configured key is ``KEY``, and a ``Run`` over it."""
    root, fastmcp = logging.getLogger(), logging.getLogger("fastmcp")
    saved = (list(root.handlers), root.level, list(fastmcp.handlers), fastmcp.propagate)

    async def build(responder=None):
        w = await research_world(responder or respond_with(KEY_FREE), clock=Clock(), api_key=KEY)
        return Run(w, caplog, capsys)

    yield build
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    fastmcp.handlers[:] = saved[2]
    fastmcp.propagate = saved[3]


def walk(value: Any, path: str = ""):
    """``(normalized path, string)`` of every string inside a JSON value (list indexes are
    written ``[]``)."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item, f"{path}[]")


# The content fields design D14 carves out, as they appear in a result and in the database.
CONTENT_RESULT_PATHS = {
    "answer",
    "sources[].title",
    "sources[].url",
    "chat.title",
    "chats[].title",
    "messages[].content",
    "messages[].sources[].title",
    "messages[].sources[].url",
    "job.query_excerpt",
    "jobs[].query_excerpt",
}
CONTENT_COLUMNS = {
    ("chats", "title"),
    ("chat_messages", "content"),
    ("chat_messages", "sources_json"),
    ("research_jobs", "query"),
    ("research_jobs", "result_text"),
    ("research_jobs", "sources_json"),
}

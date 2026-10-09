"""Task 5.1: one usage event per costed call across all four tools, in one run over the real MCP
transport (streamable HTTP on an ephemeral port).

``perplexity_ask`` once, ``perplexity_chat`` send twice, ``perplexity_research`` submit once and
``perplexity_jobs`` observing that run completed make exactly four events. Every submit, pending
poll, list, read, delete and models call in between makes none."""

import json

import httpx2
import pytest
from agent_support import fixture
from chat_support import FIRST, FOLLOW_UP, TURN_A, TURN_B
from fastmcp import Client
from research_support import COMPLETED, IN_PROGRESS, RUN_ID, SUBMIT
from server_support import free_port, serving
from sqlalchemy import text
from usage_support import Upstream

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

ASK = "agent_fast.json"
# The reported cost of each costed response, in nano-USD, written out by hand from the
# fixtures' ``usage.cost.total_cost`` (0.00125, 0.00119, 0.0018 and 0.01599 USD); the test does
# not compute it from the same parser the recorder uses.
EXPECTED_NANO = {
    "perplexity_ask": [1_250_000],
    "perplexity_chat": [1_190_000, 1_800_000],
    "perplexity_research": [15_990_000],
}
EXPECTED_TOTAL_NANO = 1_250_000 + 1_190_000 + 1_800_000 + 15_990_000  # 20_230_000 = 0.02023 USD


class Scripted:
    """The upstream: synchronous POSTs answer in turn (ask, chat, chat), a background POST is the
    research submit, the first poll of the run is in progress and every later one completed."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []
        self.sync_posts = 0
        self.polls = 0

    def __call__(self, request: httpx2.Request, n: int) -> httpx2.Response:
        self.log.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/v1/models":
            return httpx2.Response(200, json=fixture("models.json"))
        if request.method == "GET":
            self.polls += 1
            return httpx2.Response(200, json=fixture(IN_PROGRESS if self.polls == 1 else COMPLETED))
        if json.loads(request.content).get("background") is True:
            return httpx2.Response(200, json=fixture(SUBMIT))
        self.sync_posts += 1
        return httpx2.Response(200, json=fixture([ASK, TURN_A, TURN_B][self.sync_posts - 1]))


@pytest.fixture
async def running(make_settings):
    settings = make_settings()
    migrate(settings)
    engine = create_engine_for(settings)
    script = Scripted()
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(Upstream(script)))
    server = build_server(settings, http, engine)
    settings.port = free_port()
    async with serving(server, settings):
        yield f"http://127.0.0.1:{settings.port}/mcp", engine, script
    await http.aclose()
    await engine.dispose()


async def events(engine) -> list[tuple]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT tool, api, status, preset, model, request_id, cost_nano_usd, cost_source "
                "FROM usage_events ORDER BY id"
            )
        )
        return [tuple(r) for r in rows]


async def test_four_costed_calls_make_four_events_and_nothing_else_does(running):
    url, engine, script = running
    async with Client(url) as client:

        async def call(tool, **arguments):
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result.content
            return result.structured_content

        async def settled(expected: int, what: str) -> None:
            assert len(await events(engine)) == expected, what

        await call("perplexity_ask", query="What is new in Python?")
        await settled(1, "ask")
        sent = await call("perplexity_chat", action="send", message=FIRST, title="Teal notes")
        chat_id = sent["chat_id"]
        await call("perplexity_chat", action="send", chat_id=chat_id, message=FOLLOW_UP)
        await settled(3, "two chat sends")

        submitted = await call("perplexity_research", query="compare vector databases")
        job_id = submitted["job_id"]
        assert submitted["status"] == "queued"
        await settled(3, "a queued submit records nothing")

        pending = await call("perplexity_jobs", action="status", job_id=job_id)
        assert pending["status"] == "in_progress"
        await settled(3, "a pending poll records nothing")

        await call("perplexity_jobs", action="list")  # no refresh: no fetch, no event
        await call("perplexity_chat", action="list")
        await call("perplexity_chat", action="read", chat_id=chat_id)
        await call("perplexity_models")
        await settled(3, "list, read and models record nothing")

        done = await call("perplexity_jobs", action="status", job_id=job_id)
        assert done["status"] == "completed"
        await settled(4, "the observation that sees the run finish")

        await call("perplexity_jobs", action="result", job_id=job_id)  # served locally
        await call("perplexity_jobs", action="list", refresh=True)  # nothing running any more
        await call("perplexity_chat", action="delete", chat_id=chat_id, confirm=True)
        await settled(4, "result, a settled refresh and delete record nothing")

        by_api = (
            await client.call_tool("perplexity_usage", {"group_by": "api"})
        ).structured_content
        by_tool = (
            await client.call_tool("perplexity_usage", {"group_by": "tool"})
        ).structured_content

    rows = await events(engine)
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("perplexity_ask", "agent", "ok"),
        ("perplexity_chat", "agent", "ok"),
        ("perplexity_chat", "agent", "ok"),
        ("perplexity_research", "agent", "ok"),
    ]
    assert [r[3] for r in rows] == ["fast", "fast", "fast", "medium"]
    assert len({r[5] for r in rows}) == 4  # four distinct response ids
    assert rows[3][5] == RUN_ID and rows[3][4] == "openai/gpt-6-luna"
    assert all(r[7] == "reported" for r in rows)
    for tool, expected in EXPECTED_NANO.items():
        assert [r[6] for r in rows if r[0] == tool] == expected
    assert sum(r[6] for r in rows) == EXPECTED_TOTAL_NANO

    (agent_group,) = by_api["groups"]  # only the Agent API family appears
    assert agent_group["key"] == "agent" and agent_group["calls"] == 4
    assert agent_group["cost_nano_usd"] == by_api["totals"]["cost_nano_usd"] == EXPECTED_TOTAL_NANO
    assert by_api["totals"]["cost_usd"] == "0.02023"
    assert {g["key"]: g["calls"] for g in by_tool["groups"]} == {
        "perplexity_ask": 1,
        "perplexity_chat": 2,
        "perplexity_research": 1,
    }
    # exactly the calls that were meant to reach the API did: 3 sync POSTs, 1 submit, 2 polls,
    # and the one catalog fetch (the cancel endpoint was never used)
    assert sorted(script.log) == sorted(
        [("POST", "/v1/agent")] * 4 + [("GET", f"/v1/agent/{RUN_ID}")] * 2 + [("GET", "/v1/models")]
    )

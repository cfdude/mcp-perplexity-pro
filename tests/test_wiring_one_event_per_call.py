"""Task 5.1: one usage event per costed call across all seven costed tools, in one run over the
real MCP transport (streamable HTTP on an ephemeral port).

``perplexity_ask`` once, ``perplexity_chat`` send twice, ``perplexity_search`` twice (a fast and
a three-query web search), ``perplexity_decide`` once, ``perplexity_embed`` index and search
once each, ``perplexity_research`` submit once and ``perplexity_jobs`` observing that run
completed make exactly nine events. Every submit, pending
poll, list, read, delete and models call in between makes none."""

import json

import httpx2
import pytest
from agent_support import fixture
from chat_support import FIRST, FOLLOW_UP, TURN_A, TURN_B
from fastmcp import Client
from fixture_support import FIXTURE_DIR
from research_support import COMPLETED, IN_PROGRESS, RUN_ID, SUBMIT
from server_support import free_port, serving
from sqlalchemy import text
from usage_support import Upstream

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

ASK = "agent_fast.json"
DECISION = "decisions_three_questions.json"
# the index of two texts (0.6b, 128 dimensions: 14 tokens, 5.6e-08 USD) and the query embedding
# (one input, 0.6b, 128 dimensions: 2 tokens, 8e-09 USD)
EMBEDDINGS = ["embeddings_unicode_06b.json", "embeddings_int8_explicit_06b.json"]
SEARCHES = ["search_fast_single.json", "search_web_single.json"]  # distinct ids: both are stored
# The reported cost of each costed response, in nano-USD, written out by hand from the
# fixtures' ``usage.cost.total_cost`` (0.00125, 0.00119, 0.0018 and 0.01599 USD); the test does
# not compute it from the same parser the recorder uses.
EXPECTED_NANO = {
    "perplexity_ask": [1_250_000],
    "perplexity_chat": [1_190_000, 1_800_000],
    "perplexity_research": [15_990_000],
    "perplexity_search": [1_000_000, 5_000_000],  # computed: fast $0.001, web $0.005
    "perplexity_decide": [6_940],  # computed: 347 input tokens at 20 nano-USD
    "perplexity_embed": [56, 8],  # reported: 5.6e-08 and 8e-09 USD
}
# 26_236_940 (agent, search, decisions) + 56 + 8 = 26_237_004 = 0.026237004 USD
EXPECTED_TOTAL_NANO = 26_230_000 + 6_940 + 56 + 8


class Scripted:
    """The upstream: synchronous POSTs answer in turn (ask, chat, chat), a background POST is the
    research submit, the first poll of the run is in progress and every later one completed."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []
        self.sync_posts = 0
        self.searches = 0
        self.embeds = 0
        self.polls = 0

    def __call__(self, request: httpx2.Request, n: int) -> httpx2.Response:
        self.log.append((request.method, request.url.path))
        if request.url.path == "/v1/decisions":
            return httpx2.Response(200, json=fixture(DECISION))
        if request.url.path == "/v1/embeddings":
            self.embeds += 1
            return httpx2.Response(200, json=fixture(EMBEDDINGS[self.embeds - 1]))
        if request.url.path == "/search":
            self.searches += 1
            return httpx2.Response(200, json=fixture(SEARCHES[self.searches - 1]))
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


async def test_nine_costed_calls_make_nine_events_and_nothing_else_does(running):
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
        await call("perplexity_search", query="python asyncio taskgroup", max_results=5)
        found = await call(
            "perplexity_search",
            query=["rust borrow checker", "golang generics", "zig comptime"],
            search_type="web",
        )
        assert found["query_count"] == 3
        await settled(5, "a fast and a web search")
        req = json.loads((FIXTURE_DIR / "decisions_three_questions.meta.json").read_text())[
            "request"
        ]
        decided = await call("perplexity_decide", state=req["state"], questions=req["questions"])
        assert decided["input_tokens"] == 347
        await settled(6, "a decision")
        indexed = await call(
            "perplexity_embed",
            action="index",
            source="text",
            items=[
                {"key": "alpha", "text": "日本語のテキスト"},
                {"key": "beta", "text": "émojis and accents"},
            ],
            dimensions=128,
        )
        assert (indexed["embedded_chunks"], indexed["requests"]) == (2, 1)
        await settled(7, "an embeddings index")
        again = await call(
            "perplexity_embed",
            action="index",
            source="text",
            items=[
                {"key": "alpha", "text": "日本語のテキスト"},
                {"key": "beta", "text": "émojis and accents"},
            ],
            dimensions=128,
        )
        assert again["requests"] == 0 and again["skipped_items"] == 2
        await settled(7, "a repeated index sends and records nothing")
        found_chunks = await call(
            "perplexity_embed", action="search", query="hello", dimensions=128
        )
        assert len(found_chunks["hits"]) == 2
        await settled(8, "an embeddings search")
        status = await call("perplexity_embed", action="status", dimensions=128)
        assert status["groups"][0]["chunks"] == 2
        await settled(8, "status records nothing")

        submitted = await call("perplexity_research", query="compare vector databases")
        job_id = submitted["job_id"]
        assert submitted["status"] == "queued"
        await settled(8, "a queued submit records nothing")

        pending = await call("perplexity_jobs", action="status", job_id=job_id)
        assert pending["status"] == "in_progress"
        await settled(8, "a pending poll records nothing")

        await call("perplexity_jobs", action="list")  # no refresh: no fetch, no event
        await call("perplexity_chat", action="list")
        await call("perplexity_chat", action="read", chat_id=chat_id)
        await call("perplexity_models")
        await settled(8, "list, read and models record nothing")

        done = await call("perplexity_jobs", action="status", job_id=job_id)
        assert done["status"] == "completed"
        await settled(9, "the observation that sees the run finish")

        await call("perplexity_jobs", action="result", job_id=job_id)  # served locally
        await call("perplexity_jobs", action="list", refresh=True)  # nothing running any more
        await call("perplexity_chat", action="delete", chat_id=chat_id, confirm=True)
        await settled(9, "result, a settled refresh and delete record nothing")

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
        ("perplexity_search", "search", "ok"),
        ("perplexity_search", "search", "ok"),
        ("perplexity_decide", "decisions", "ok"),
        ("perplexity_embed", "embeddings", "ok"),
        ("perplexity_embed", "embeddings", "ok"),
        ("perplexity_research", "agent", "ok"),
    ]
    agent_rows = [r for r in rows if r[1] == "agent"]
    search_rows = [r for r in rows if r[1] == "search"]
    (decision_row,) = [r for r in rows if r[1] == "decisions"]
    embed_rows = [r for r in rows if r[1] == "embeddings"]
    assert [r[3] for r in agent_rows] == [None, None, None, "medium"]
    assert all(r[3] is None and r[4] is None for r in search_rows)  # no preset, no model
    assert decision_row[3] is None and decision_row[4] == "pplx-decider-v1.1-27b"
    assert decision_row[5] is None and decision_row[7] == "computed"  # no request id
    assert all(r[3] is None and r[4] == "pplx-embed-v1-0.6b" for r in embed_rows)
    assert all(r[5] is None and r[7] == "reported" for r in embed_rows)  # no request id
    assert len({r[5] for r in rows if r[5]}) == 6  # six distinct request ids (decide, embed: none)
    assert agent_rows[3][5] == RUN_ID and agent_rows[3][4] == "openai/gpt-6-luna"
    assert all(r[7] == "reported" for r in agent_rows)
    assert all(r[7] == "computed" for r in search_rows)
    for tool, expected in EXPECTED_NANO.items():
        assert [r[6] for r in rows if r[0] == tool] == expected
    assert sum(r[6] for r in rows) == EXPECTED_TOTAL_NANO

    groups = {g["key"]: g for g in by_api["groups"]}
    assert set(groups) == {"agent", "search", "decisions", "embeddings"}
    assert groups["embeddings"]["calls"] == 2 and groups["embeddings"]["cost_nano_usd"] == 64
    assert groups["decisions"]["calls"] == 1 and groups["decisions"]["cost_nano_usd"] == 6_940
    assert groups["agent"]["calls"] == 4 and groups["search"]["calls"] == 2
    assert groups["search"]["cost_nano_usd"] == 6_000_000
    assert groups["search"]["calls_cost_computed"] == 2  # all computed, none reported
    assert groups["search"]["calls_cost_unknown"] == 0
    assert sum(g["cost_nano_usd"] for g in groups.values()) == EXPECTED_TOTAL_NANO
    assert by_api["totals"]["cost_nano_usd"] == EXPECTED_TOTAL_NANO
    assert by_api["totals"]["cost_usd"] == "0.026237004"
    assert {g["key"]: g["calls"] for g in by_tool["groups"]} == {
        "perplexity_ask": 1,
        "perplexity_chat": 2,
        "perplexity_research": 1,
        "perplexity_search": 2,
        "perplexity_decide": 1,
        "perplexity_embed": 2,
    }
    # exactly the calls that were meant to reach the API did: 3 sync POSTs, 1 submit, 2 polls,
    # 2 searches and the one catalog fetch (the cancel endpoint was never used)
    assert sorted(script.log) == sorted(
        [("POST", "/v1/agent")] * 4
        + [("POST", "/search")] * 2
        + [("POST", "/v1/decisions")]
        + [("POST", "/v1/embeddings")] * 2
        + [("GET", f"/v1/agent/{RUN_ID}")] * 2
        + [("GET", "/v1/models")]
    )

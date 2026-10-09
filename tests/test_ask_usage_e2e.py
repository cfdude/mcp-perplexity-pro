"""Task 2.5: ask recording and reporting end to end over the real MCP transport (streamable HTTP
on an ephemeral port): two projects, then ``perplexity_usage``."""

import httpx2
import pytest
from agent_support import fixture, respond_with
from fastmcp import Client
from server_support import free_port, serving
from sqlalchemy import text
from usage_support import Upstream, event_count

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "population": {"type": "integer"}},
    "required": ["city", "population"],
}


@pytest.fixture
async def running(make_settings):
    settings = make_settings()
    migrate(settings)
    engine = create_engine_for(settings)
    upstream = Upstream(respond_with("agent_fast_filters.json"))
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
    server = build_server(settings, http, engine)
    settings.port = free_port()
    async with serving(server, settings):
        yield f"http://127.0.0.1:{settings.port}/mcp", upstream, engine
    await http.aclose()
    await engine.dispose()


async def test_two_asks_are_recorded_and_reported_by_tool_and_project(running):
    url, upstream, engine = running
    async with Client(url) as client:
        first = await client.call_tool(
            "perplexity_ask",
            {
                "query": "What is new in the latest Python release?",
                "depth": "fast",
                "project": "alpha",
            },
        )
        upstream.responder = respond_with("agent_structured_output.json")
        second = await client.call_tool(
            "perplexity_ask",
            {"query": "Capital of France?", "json_schema": SCHEMA, "project": "beta"},
        )
        assert first.structured_content["usage"]["cost_usd"] == "0.00163"
        assert second.structured_content["answer_json"] == {"city": "Paris", "population": 2050000}

        # a free call records nothing
        upstream.responder = respond_with("models.json")
        before = await event_count(engine)
        models = await client.call_tool("perplexity_models", {}, raise_on_error=False)
        assert not models.is_error and await event_count(engine) == before == 2

        by_tool = (
            await client.call_tool("perplexity_usage", {"group_by": "tool"})
        ).structured_content
        by_project = (
            await client.call_tool("perplexity_usage", {"group_by": "project"})
        ).structured_content
        by_api = (
            await client.call_tool("perplexity_usage", {"group_by": "api"})
        ).structured_content

    async with engine.connect() as conn:
        rows = list(
            await conn.execute(
                text(
                    "SELECT project_name, cost_nano_usd, cost_source, status, tool, api "
                    "FROM usage_events ORDER BY id"
                )
            )
        )
    assert [tuple(r) for r in rows] == [
        ("alpha", 1_630_000, "reported", "ok", "perplexity_ask", "agent"),
        ("beta", 1_470_000, "reported", "ok", "perplexity_ask", "agent"),
    ]
    assert fixture("agent_fast_filters.json")["usage"]["cost"]["total_cost"] == 0.00163

    totals = by_tool["totals"]
    assert (totals["cost_nano_usd"], totals["cost_usd"], totals["calls"]) == (
        3_100_000,
        "0.0031",
        2,
    )
    assert [(g["key"], g["calls"], g["cost_nano_usd"]) for g in by_tool["groups"]] == [
        ("perplexity_ask", 2, 3_100_000)
    ]
    groups = {g["key"]: g for g in by_project["groups"]}
    assert set(groups) == {"alpha", "beta"}
    assert (groups["alpha"]["cost_nano_usd"], groups["beta"]["cost_nano_usd"]) == (
        1_630_000,
        1_470_000,
    )
    assert [g["key"] for g in by_api["groups"]] == ["agent"]

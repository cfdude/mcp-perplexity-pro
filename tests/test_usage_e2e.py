"""Task 5.3: end to end over the real MCP transport (streamable HTTP on an ephemeral port).

The TEST-ONLY caller of ``usage_support`` makes costed calls for two projects through the
production server factory; one project is then deleted with ``perplexity_projects`` and
``perplexity_usage`` reports the spend, all in one running server.
"""

import json
from datetime import UTC, datetime

import httpx2
import pytest
from fastmcp import Client
from fixture_support import FIXTURE_DIR
from server_support import free_port, serving
from sqlalchemy import text
from usage_support import TOOL, Upstream, add_test_tool, event_count

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate


def fixture_body(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def respond_with(name):
    return lambda request, n: httpx2.Response(200, json=fixture_body(name))


def rate_limited(request, n):
    return httpx2.Response(
        429, json={"error": {"message": "slow down"}}, headers={"Retry-After": "3600"}
    )


@pytest.fixture
async def running(make_settings):
    settings = make_settings()
    migrate(settings)
    engine = create_engine_for(settings)
    upstream = Upstream(respond_with("agent_fast.json"))
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
    server = build_server(settings, http, engine)
    add_test_tool(server)
    settings.port = free_port()
    async with serving(server, settings):
        yield f"http://127.0.0.1:{settings.port}/mcp", upstream, engine
    await http.aclose()
    await engine.dispose()


async def test_spend_for_two_projects_is_reported_after_one_is_deleted(running):
    url, upstream, engine = running
    async with Client(url) as client:
        # alpha: a completed Agent response (1,250,000 nano-USD reported)
        await client.call_tool(TOOL, {"project": "alpha"})
        # beta: the completed background response (1,050,000) fetched twice, then a rate limit
        upstream.responder = respond_with("agent_background_poll.json")
        await client.call_tool(TOOL, {"project": "beta"})
        await client.call_tool(TOOL, {"project": "beta"})
        upstream.responder = rate_limited
        failed = await client.call_tool(TOOL, {"project": "beta"}, raise_on_error=False)
        assert failed.is_error and failed.structured_content["category"] == "rate_limited"

        # a free call records nothing
        before = await event_count(engine)
        upstream.responder = respond_with("models.json")
        models = await client.call_tool("perplexity_models", {}, raise_on_error=False)
        assert not models.is_error
        assert await event_count(engine) == before == 3

        deleted = await client.call_tool(
            "perplexity_projects", {"action": "delete", "project": "alpha", "confirm": True}
        )
        assert deleted.structured_content["rows_retained"] == 1

        by_project = (
            await client.call_tool("perplexity_usage", {"group_by": "project"})
        ).structured_content
        by_tool = (
            await client.call_tool("perplexity_usage", {"group_by": "tool"})
        ).structured_content
        by_day = (
            await client.call_tool("perplexity_usage", {"group_by": "day"})
        ).structured_content
        alpha_only = (
            await client.call_tool("perplexity_usage", {"project": "alpha"})
        ).structured_content

    totals = by_project["totals"]
    assert totals["cost_nano_usd"] == 1_250_000 + 1_050_000  # the two successful runs
    assert totals["cost_usd"] == "0.0023"
    assert (totals["calls"], totals["errors"]) == (3, 1)  # the repeated response counted once
    assert totals["calls_cost_unknown"] == 1  # the rate-limited failure: cost 0, source none

    groups = {g["key"]: g for g in by_project["groups"]}
    assert set(groups) == {"alpha", "beta"}  # the deleted project's history, under its name
    assert (groups["alpha"]["calls"], groups["alpha"]["cost_nano_usd"]) == (1, 1_250_000)
    assert (groups["beta"]["calls"], groups["beta"]["errors"]) == (2, 1)
    assert groups["beta"]["cost_nano_usd"] == 1_050_000
    assert [g["key"] for g in by_project["groups"]] == ["alpha", "beta"]  # cost descending

    assert [(g["key"], g["calls"]) for g in by_tool["groups"]] == [(TOOL, 3)]
    days = [g["key"] for g in by_day["groups"]]  # one UTC day, or two if the run crossed midnight
    assert days == sorted(days) and sum(g["calls"] for g in by_day["groups"]) == 3
    assert days[-1] == datetime.now(UTC).strftime("%Y-%m-%d") or len(days) == 2
    assert alpha_only["totals"]["cost_nano_usd"] == 1_250_000

    async with engine.connect() as conn:
        detached = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM usage_events "
                    "WHERE project_name='alpha' AND project_id IS NULL"
                )
            )
        ).scalar_one()
        names = list((await conn.execute(text("SELECT name FROM projects"))).scalars())
    assert detached == 1 and names == ["beta"]

"""Task 4.6: job recording end to end over the real MCP transport (streamable HTTP on an
ephemeral port): two research runs are submitted, one is observed completed and one cancelled
through ``perplexity_jobs``, and ``perplexity_usage`` reports them by tool."""

import httpx2
import pytest
from agent_support import fixture
from fastmcp import Client
from research_support import CANCELLED, CANCELLED_ID, COMPLETED, RUN_ID, SUBMIT
from server_support import free_port, serving
from usage_support import Upstream, event_count

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

SUBMITS = {
    1: fixture(SUBMIT),  # run A: queued, completes later
    2: {**fixture(SUBMIT), "id": CANCELLED_ID},  # run B: queued, is cancelled later
}


def responder(request, n):
    """Submits answer queued bodies in turn; a GET answers by the run's id in the path."""
    if request.method == "POST":
        posts = [r for r in log if r.method == "POST"]
        return httpx2.Response(200, json=SUBMITS[len(posts)])
    body = fixture(COMPLETED if request.url.path.endswith(RUN_ID) else CANCELLED)
    return httpx2.Response(200, json=body)


log: list[httpx2.Request] = []


@pytest.fixture
async def running(make_settings):
    log.clear()
    settings = make_settings()
    migrate(settings)
    engine = create_engine_for(settings)

    def record(request, n):
        log.append(request)
        return responder(request, n)

    upstream = Upstream(record)
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
    server = build_server(settings, http, engine)
    settings.port = free_port()
    async with serving(server, settings):
        yield f"http://127.0.0.1:{settings.port}/mcp", engine
    await http.aclose()
    await engine.dispose()


async def test_two_runs_one_completed_and_one_cancelled_are_recorded_once_each(running):
    url, engine = running
    async with Client(url) as client:
        a = await client.call_tool(
            "perplexity_research", {"query": "compare vector databases", "project": "lab"}
        )
        b = await client.call_tool(
            "perplexity_research", {"query": "another run", "project": "lab"}
        )
        job_a, job_b = a.structured_content["job_id"], b.structured_content["job_id"]
        assert [a.structured_content["status"], b.structured_content["status"]] == ["queued"] * 2
        assert await event_count(engine) == 0  # the submits recorded nothing

        done = await client.call_tool(
            "perplexity_jobs", {"action": "status", "job_id": job_a, "project": "lab"}
        )
        gone = await client.call_tool(
            "perplexity_jobs", {"action": "status", "job_id": job_b, "project": "lab"}
        )
        assert (done.structured_content["status"], gone.structured_content["status"]) == (
            "completed",
            "cancelled",
        )
        assert await event_count(engine) == 2
        fetches = len([r for r in log if r.method == "GET"])

        for action, job_id in (
            ("status", job_a),
            ("result", job_a),
            ("status", job_b),
            ("result", job_b),
        ):  # a finished job is served locally: no fetch, no event
            again = await client.call_tool(
                "perplexity_jobs", {"action": action, "job_id": job_id, "project": "lab"}
            )
            assert not again.is_error
        assert await event_count(engine) == 2
        assert len([r for r in log if r.method == "GET"]) == fetches == 2

        by_tool = (
            await client.call_tool("perplexity_usage", {"group_by": "tool"})
        ).structured_content
        by_api = (
            await client.call_tool("perplexity_usage", {"group_by": "api"})
        ).structured_content

    (group,) = by_tool["groups"]
    assert group["key"] == "perplexity_research"
    assert (group["calls"], group["errors"], group["calls_cost_unknown"]) == (2, 1, 1)
    assert group["cost_nano_usd"] == by_tool["totals"]["cost_nano_usd"] == 15990000
    assert group["cost_usd"] == "0.01599"
    assert [g["key"] for g in by_api["groups"]] == ["agent"]
    # both submits and every poll went out as the one POST /v1/agent each and plain GETs
    assert [f"{r.method} {r.url.path}" for r in log].count("POST /v1/agent") == 2

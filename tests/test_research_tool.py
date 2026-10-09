"""Task 4.2: ``perplexity_research`` through ``build_server`` (agent-research "Research tool",
"Runs are background and retrievable", "Submit is not a costed call yet", "Submit that returns
another status", "A started run is never orphaned silently")."""

import asyncio
import logging

import httpx2
import jsonschema
import pytest
from agent_support import fixture, inline
from chat_support import category, message
from research_support import (
    COMPLETED,
    RUN_ID,
    Clock,
    job,
    job_rows,
    request_log,
    routes,
)

import mcp_perplexity_pro.tools.research as research_module

TOOL = "perplexity_research"
KEY = "test-dummy-api-key"
QUERY = fixture("agent_background_submit_medium.meta.json")["request"]["input"]


async def nothing_happened(w):
    assert w.requests == []
    assert await w.count("usage_events") == 0
    assert await w.count("research_jobs") == 0
    assert await w.count("projects") == 0


# --- submit and the request ------------------------------------------------------------------


async def test_a_queued_submit_creates_a_job_and_records_nothing(research_world):
    w = await research_world(clock=Clock())
    result = await w.call(TOOL, query=QUERY)
    out = result.structured_content
    assert not result.is_error
    assert (out["status"], out["depth"], out["response_id"]) == ("queued", "medium", RUN_ID)
    assert out["project"] == "default" and isinstance(out["job_id"], int)
    row = await job(w, out["job_id"])
    assert (row["status"], row["response_id"], row["query"]) == ("queued", RUN_ID, QUERY)
    assert row["usage_recorded"] == 0 and row["model"] is None  # the API's "medium" is no model
    assert row["started_at"].startswith("2026-10-09 12:00:00")  # OUR clock, at submission
    assert await w.count("usage_events") == 0
    assert "perplexity_jobs" in result.content[0].text


async def test_the_default_depth_request_is_the_recorded_one_plus_store_true(research_world):
    w = await research_world()
    await w.call(TOOL, query=QUERY)
    sidecar = fixture("agent_background_submit_medium.meta.json")["request"]
    assert sidecar == {"preset": "medium", "background": True, "input": QUERY}
    assert w.bodies() == [{**sidecar, "store": True}]


async def test_the_accepted_run_trail_is_logged_at_info_before_the_row_is_stored(
    research_world, caplog
):
    w = await research_world()
    with caplog.at_level(logging.INFO):
        await w.call(TOOL, query=QUERY)
    trail = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO and "accepted by the provider" in r.getMessage()
    ]
    assert len(trail) == 1 and RUN_ID in trail[0].getMessage()
    assert KEY not in caplog.text


async def test_a_high_submit_request_has_no_sidecar_and_is_asserted_inline(research_world):
    w = await research_world()
    await w.call(TOOL, query=QUERY, depth="high")
    # NOT backed by a recording: no `high` run was ever captured (design D11)
    expected = {"preset": "high", "background": True, "store": True, "input": QUERY}
    assert w.bodies() == [expected]


@pytest.mark.parametrize("depth", ["medium", "high", "xhigh"])
async def test_every_research_request_is_background_and_stored(research_world, depth):
    w = await research_world()
    await w.call(TOOL, query="q", depth=depth, instructions="be brief")
    (body,) = w.bodies()
    assert (body["preset"], body["background"], body["store"]) == (depth, True, True)
    assert body["instructions"] == "be brief"


async def test_there_is_no_way_to_send_store_false(research_world):
    from fastmcp import Client

    w = await research_world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    assert not {"store", "background"} & set(tool.input_schema["properties"])
    result = await w.call(TOOL, query="q", store=False)  # an unknown argument is refused
    assert result.is_error
    assert w.requests == []


@pytest.mark.parametrize(
    ("arguments", "needle"),
    [
        ({"query": ""}, "query"),
        ({"query": "   "}, "query"),
        ({"query": "x" * 20001}, "query"),
        ({"query": "q", "depth": "fast"}, "perplexity_ask"),
        ({"query": "q", "depth": "low"}, "perplexity_ask"),
        ({"query": "q", "instructions": "x" * 10001}, "instructions"),
    ],
)
async def test_bad_input_fails_before_any_request_job_or_project(research_world, arguments, needle):
    w = await research_world()
    result = await w.call(TOOL, project="never", **arguments)
    assert category(result) == "invalid_request" and needle in message(result)
    await nothing_happened(w)


async def test_a_query_of_exactly_20000_characters_is_sent(research_world):
    w = await research_world()
    assert not (await w.call(TOOL, query="x" * 20000)).is_error
    assert w.bodies()[0]["input"] == "x" * 20000


async def test_the_project_is_created_and_the_job_belongs_to_it(research_world):
    w = await research_world()
    out = (await w.call(TOOL, query="q", project="alpha")).structured_content
    assert out["project"] == "alpha"
    assert await w.rows(
        "SELECT p.name FROM research_jobs j JOIN projects p ON p.id=j.project_id"
    ) == [("alpha",)]


# --- a submit that comes back finished -------------------------------------------------------


async def test_a_submit_that_returns_completed_is_stored_terminal_and_recorded_once(
    research_world,
):
    w = await research_world(routes(post=[COMPLETED]))
    out = (await w.call(TOOL, query=QUERY)).structured_content
    assert out["status"] == "completed"
    row = await job(w, out["job_id"])
    raw = fixture(COMPLETED)
    answer = [i for i in raw["output"] if i["type"] == "message"][-1]["content"][-1]["text"]
    assert (row["status"], row["usage_recorded"], row["result_text"]) == ("completed", 1, answer)
    assert (row["model"], row["cost_nano_usd"], row["cost_source"]) == (
        "openai/gpt-6-luna",
        15990000,
        "reported",
    )
    assert (row["input_tokens"], row["output_tokens"], row["total_tokens"]) == (24463, 1085, 25548)
    assert row["finished_at"] is not None and row["last_checked_at"] is None
    assert await w.events() == [
        (
            TOOL,
            "agent",
            "ok",
            "medium",
            "openai/gpt-6-luna",
            RUN_ID,
            "default",
            15990000,
            "reported",
        )
    ]


async def test_a_failed_submit_is_a_terminal_job_and_one_unexpected_response_event(research_world):
    body = inline("failed", id="resp_failed-1", model="medium", error={"message": "boom"})
    w = await research_world(routes(post=[body]))
    out = (await w.call(TOOL, query="q")).structured_content
    assert out["status"] == "failed"
    row = await job(w, out["job_id"])
    assert (row["status"], row["usage_recorded"], row["error_text"]) == ("failed", 1, "boom")
    (event,) = await w.events()
    assert event[2] == "unexpected_response" and event[4] is None  # "medium" is no model
    assert event[7:] == (0, "none")


async def test_an_unknown_submit_status_is_stored_verbatim_as_running_with_no_event(
    research_world,
):
    w = await research_world(routes(post=[inline("paused", id="resp_paused-1")]))
    result = await w.call(TOOL, query="q")
    assert not result.is_error and result.structured_content["status"] == "paused"
    row = await job(w, result.structured_content["job_id"])
    assert (row["status"], row["usage_recorded"], row["finished_at"]) == ("paused", 0, None)
    assert await w.count("usage_events") == 0


async def test_an_unknown_status_is_redacted_and_cut_to_64_characters(research_world):
    odd = "pplx-" + "Ab1_" * 12 + "z" * 80
    w = await research_world(routes(post=[inline(odd, id="resp_odd-1")]))
    out = (await w.call(TOOL, query="q")).structured_content
    assert len(out["status"]) <= 64 and "pplx-Ab1_" not in out["status"]
    assert (await job(w, out["job_id"]))["status"] == out["status"]


# --- a failed submit -------------------------------------------------------------------------


async def test_a_429_beyond_the_maximum_wait_creates_no_job_and_records_a_failure(research_world):
    limited = httpx2.Response(
        429,
        json={"error": {"message": "slow down", "type": "rate_limit"}},
        headers={"Retry-After": "9999"},
    )
    w = await research_world(routes(post=[limited]))
    result = await w.call(TOOL, query="q")
    assert category(result) == "rate_limited"
    assert await w.count("research_jobs") == 0
    assert await w.events() == [
        (TOOL, "agent", "rate_limited", "medium", None, None, "default", 0, "none")
    ]


# --- the row insert after an accepted run ----------------------------------------------------


@pytest.fixture
def counted_inserts(monkeypatch):
    """Wrap the insert: count attempts and fail the first ``fail`` of them."""
    state = {"calls": 0, "fail": 0}
    real = research_module.insert_job

    async def wrapper(session, project_id, values):
        state["calls"] += 1
        if state["calls"] <= state["fail"]:
            raise RuntimeError("disk is on fire")
        return await real(session, project_id, values)

    monkeypatch.setattr(research_module, "insert_job", wrapper)
    return state


async def test_an_insert_that_fails_twice_names_the_response_id_and_logs_it(
    research_world, counted_inserts, caplog
):
    counted_inserts["fail"] = 2
    w = await research_world()
    with caplog.at_level(logging.ERROR):
        result = await w.call(TOOL, query="q")
    assert category(result) == "internal_error"
    assert RUN_ID in message(result) and "cancel" in message(result)
    assert counted_inserts["calls"] == 2  # exactly one retry
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and RUN_ID in r.getMessage()]
    assert len(errors) == 1 and KEY not in errors[0].getMessage()
    assert KEY not in caplog.text and KEY not in message(result)
    assert await w.count("research_jobs") == 0


async def test_a_real_database_veto_on_the_insert_fails_the_same_way(research_world):
    w = await research_world()
    async with w.engine.begin() as conn:
        from sqlalchemy import text

        await conn.execute(
            text(
                "CREATE TRIGGER veto BEFORE INSERT ON research_jobs "
                "BEGIN SELECT RAISE(ABORT, 'vetoed'); END"
            )
        )
    result = await w.call(TOOL, query="q")
    assert category(result) == "internal_error" and RUN_ID in message(result)
    assert await w.count("research_jobs") == 0


async def test_an_insert_that_fails_once_then_succeeds_gives_a_normal_result(
    research_world, counted_inserts
):
    counted_inserts["fail"] = 1
    w = await research_world()
    result = await w.call(TOOL, query="q")
    assert not result.is_error and counted_inserts["calls"] == 2
    assert len(await job_rows(w)) == 1


@pytest.mark.parametrize(
    "bad", ["x/../y", "resp_", "resp_" + "a" * 101, "resp_a b", "", "resp_a\n"]
)
async def test_a_malformed_response_id_is_refused_and_no_row_is_inserted(research_world, bad):
    w = await research_world(routes(post=[inline("queued", id=bad)]))
    result = await w.call(TOOL, query="q")
    assert category(result) == "unexpected_response"
    assert await w.count("research_jobs") == 0


# --- listing, schema, annotations ------------------------------------------------------------


async def test_listing_has_schema_annotations_cost_and_retention_wording(research_world):
    from fastmcp import Client

    w = await research_world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    assert tool.output_schema and "job_id" in tool.output_schema["properties"]
    ann = tool.annotations
    assert (ann.read_only_hint, ann.destructive_hint, ann.open_world_hint) == (False, False, True)
    desc = " ".join(tool.description.split())
    for cost in ("$0.016 to $0.05", "$0.4 to $0.9"):
        assert cost in desc
    assert "perplexity_jobs" in desc and "estimate" in desc
    assert "stored by the provider" in desc and "store is true" in desc
    lowered = desc.lower()
    for claim in (
        "nothing is retained",
        "not retained",
        "no retention",
        "keeps nothing",
        "private",
    ):
        assert claim not in lowered, claim
    assert tool.input_schema["required"] == ["query"]
    assert tool.input_schema["properties"]["depth"]["default"] == "medium"


async def test_the_result_validates_against_the_advertised_schema(research_world):
    from fastmcp import Client

    w = await research_world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
        result = await client.call_tool(TOOL, {"query": QUERY})
    jsonschema.validate(result.structured_content, tool.output_schema)
    assert request_log(w) == ["POST /v1/agent"]


async def test_a_client_cancel_after_the_accepted_submit_still_stores_the_job_row(
    research_world, monkeypatch
):
    """The provider accepted the run: a client cancel while the row is being inserted must not
    leave a billed run with no handle (the write is shielded and finishes)."""
    w = await research_world()
    in_insert = asyncio.Event()
    real = research_module.insert_job

    async def slow_insert(session, project_id, values):
        in_insert.set()
        await asyncio.sleep(0.2)  # the client cancels the call while this is being written
        return await real(session, project_id, values)

    monkeypatch.setattr(research_module, "insert_job", slow_insert)
    task = asyncio.create_task(w.call(TOOL, query="q"))
    await asyncio.wait_for(in_insert.wait(), 5)
    assert request_log(w) == ["POST /v1/agent"]  # the provider has already accepted the run
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(50):
        if await w.count("research_jobs"):
            break
        await asyncio.sleep(0.1)
    rows = await job_rows(w)
    assert len(rows) == 1 and rows[0]["response_id"] == RUN_ID

"""Task 2.4: ``perplexity_ask`` through ``build_server`` (agent-ask scenarios)."""

import asyncio
import logging

import httpx2
import jsonschema
import pytest
from agent_support import fixture, inline, make_world, respond_body, respond_with
from usage_support import DbLock

from mcp_perplexity_pro.storage.engine import database_path

TOOL = "perplexity_ask"
KEY = "test-dummy-api-key"
TOKEN = "pplx-" + "Qq7_" * 12
SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "population": {"type": "integer"}},
    "required": ["city", "population"],
}


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder=None, **settings):
        w = await make_world(
            make_settings, responder or respond_with("agent_fast.json"), **settings
        )
        made.append(w)
        return w

    yield build
    for w in made:
        await w.aclose()


def category(result):
    assert result.is_error
    return result.structured_content["category"]


def message(result):
    return result.structured_content["message"]


async def nothing_happened(w):
    assert w.requests == []
    assert await w.count("usage_events") == 0
    assert await w.count("projects") == 0


# --- tool listing and result shape -----------------------------------------------------------


async def test_listing_has_schema_annotations_costs_and_the_honest_wording(world):
    from fastmcp import Client

    w = await world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    assert tool.output_schema and "answer" in tool.output_schema["properties"]
    ann = tool.annotations
    assert (ann.read_only_hint, ann.destructive_hint, ann.open_world_hint) == (False, False, True)
    desc = " ".join(tool.description.split())  # the docstring wraps lines
    for cost in ("$0.001 to $0.002", "$0.0005 to $0.004", "$0.016 to $0.017"):
        assert cost in desc
    assert "perplexity_research" in desc
    assert "web search tool alone" in desc  # a filter replaces the preset's own tools
    assert "only hides" in desc and "retrieval" in desc  # what store false does
    lowered = desc.lower()
    for claim in (
        "nothing is retained",
        "not retained",
        "no retention",
        "keeps nothing",
        "deletes",
        "never stored",
        "not stored",
        "private",
    ):
        assert claim not in lowered, claim
    for name in ("query", "depth", "model", "search", "domains", "json_schema", "project"):
        assert name in tool.input_schema["properties"]
    assert tool.input_schema["required"] == ["query"]


async def test_the_result_validates_against_the_advertised_schema(world):
    from fastmcp import Client

    w = await world(respond_with("agent_fast_filters.json"))
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
        result = await client.call_tool(TOOL, {"query": "What is new in Python?"})
    jsonschema.validate(result.structured_content, tool.output_schema)
    raw = fixture("agent_fast_filters.json")
    final = [i for i in raw["output"] if i["type"] == "message"][-1]["content"][-1]["text"]
    assert final in result.content[0].text  # the text content carries the answer


async def test_the_completed_answer_sources_model_depth_and_status(world):
    w = await world(respond_with("agent_fast_filters.json"))
    result = await w.call(TOOL, query="What is new?")
    out = result.structured_content
    raw = fixture("agent_fast_filters.json")
    final = [i for i in raw["output"] if i["type"] == "message"][-1]["content"][-1]["text"]
    urls = [r["url"] for i in raw["output"] if i["type"] == "search_results" for r in i["results"]]
    assert out["answer"] == final  # inline markers untouched
    assert [s["url"] for s in out["sources"]] == urls
    assert (out["model"], out["depth"], out["status"]) == ("openai/gpt-6-luna", "fast", "completed")
    assert out["response_id"] == raw["id"] and out["project"] == "default"
    assert out["usage"]["cost_usd"] == "0.00163" and out["usage"]["cost_source"] == "reported"
    assert out["latency_ms"] >= 0 and out["answer_json"] is None and out["warnings"] == []
    assert "Sources" in result.content[0].text and "cost" in result.content[0].text.lower()


# --- query -----------------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["", "   ", "x" * 20001])
async def test_a_bad_query_fails_before_anything_happens(world, query):
    w = await world()
    result = await w.call(TOOL, query=query, project="never")
    assert category(result) == "invalid_request" and "query" in message(result)
    await nothing_happened(w)


async def test_a_query_of_exactly_20000_characters_is_sent(world):
    w = await world()
    assert not (await w.call(TOOL, query="x" * 20000)).is_error
    assert w.bodies()[0]["input"] == "x" * 20000


# --- depth, model and search -----------------------------------------------------------------


async def test_default_depth_sends_preset_fast_and_store_false(world):
    w = await world()
    await w.call(TOOL, query="q")
    assert w.bodies() == [{"preset": "fast", "input": "q", "store": False}]


async def test_depth_medium_names_preset_medium(world):
    w = await world()
    assert (await w.call(TOOL, query="q", depth="medium")).structured_content["depth"] == "medium"
    assert w.bodies()[0]["preset"] == "medium"


@pytest.mark.parametrize("depth", ["high", "xhigh"])
async def test_long_depths_are_refused_naming_perplexity_research(world, depth):
    w = await world()
    result = await w.call(TOOL, query="q", depth=depth)
    assert category(result) == "invalid_request" and "perplexity_research" in message(result)
    await nothing_happened(w)


async def test_a_model_with_search_names_the_model_one_tool_and_three_steps(world):
    w = await world()
    out = (await w.call(TOOL, query="q", model="openai/gpt-6-luna")).structured_content
    assert w.bodies() == [
        {
            "model": "openai/gpt-6-luna",
            "input": "q",
            "store": False,
            "tools": [{"type": "web_search"}],
            "max_steps": 3,
        }
    ]
    assert out["depth"] is None


async def test_a_model_without_search_sends_no_tools_and_has_no_sources(world):
    w = await world(respond_with("agent_model_without_tools.json"))
    out = (
        await w.call(TOOL, query="q", model="openai/gpt-6-luna", search=False)
    ).structured_content
    body = w.bodies()[0]
    assert "tools" not in body and "max_steps" not in body and "preset" not in body
    assert out["sources"] == [] and out["answer"]


@pytest.mark.parametrize(
    "arguments",
    [{"depth": "low", "model": "openai/gpt-6-luna"}, {"search": False}],
    ids=["depth with model", "search false without model"],
)
async def test_conflicting_options_are_refused(world, arguments):
    w = await world()
    result = await w.call(TOOL, query="q", **arguments)
    assert category(result) == "invalid_request"
    await nothing_happened(w)


async def test_search_true_is_harmless(world):
    w = await world()
    await w.call(TOOL, query="q", depth="low")
    await w.call(TOOL, query="q", depth="low", search=True)
    await w.call(TOOL, query="q", model="openai/gpt-6-luna")
    await w.call(TOOL, query="q", model="openai/gpt-6-luna", search=True)
    a, b, c, d = w.bodies()
    assert a == b and c == d


async def test_anthropic_models_get_the_default_cap_and_an_explicit_cap_is_kept(world):
    w = await world()
    model = "anthropic/claude-haiku-4-5"
    await w.call(TOOL, query="q", model=model)
    await w.call(TOOL, query="q", model=model, max_output_tokens=200)
    assert [b["max_output_tokens"] for b in w.bodies()] == [4096, 200]


# --- instructions, caps, filters, structured output ------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "named"),
    [
        ({"max_output_tokens": 64001}, "max_output_tokens"),
        ({"max_output_tokens": 0}, "max_output_tokens"),
        ({"instructions": "x" * 10001}, "instructions"),
        ({"domains": ["python.org", "-reddit.com"]}, "domains"),
        ({"domains": [f"d{i}.com" for i in range(21)]}, "domains"),
        ({"domains": ["a.com", ""]}, "domains"),
        ({"after": "09/15/2026"}, "after"),
        ({"after": "2026-13-40"}, "after"),
        ({"after": "2026-10-01", "before": "2026-09-01"}, "after"),
        ({"recency": "fortnight"}, "recency"),
        ({"max_results": 0}, "max_results"),
        ({"country": "USA"}, "country"),
        ({"model": "openai/gpt-6-luna", "search": False, "recency": "week"}, "recency"),
        ({"json_schema": {"type": "array", "items": {}}}, "json_schema"),
        ({"project": "bad name!"}, "project"),
    ],
)
async def test_every_local_validation_failure_creates_no_project_and_no_event(
    world, arguments, named
):
    w = await world()
    result = await w.call(TOOL, query="q", **arguments)
    assert category(result) == "invalid_request" and named in message(result)
    await nothing_happened(w)


async def test_instructions_and_cap_are_passed_through(world):
    w = await world()
    await w.call(TOOL, query="q", instructions="Answer tersely.", max_output_tokens=400)
    body = w.bodies()[0]
    assert (body["instructions"], body["max_output_tokens"]) == ("Answer tersely.", 400)


async def test_filters_are_sent_as_the_web_search_tools_options(world):
    w = await world(respond_with("agent_fast_filters.json"))
    await w.call(
        TOOL,
        query="What is new in the latest Python release? Two sentences.",
        domains=["python.org"],
        recency="month",
        country="US",
        instructions="Answer tersely. Cite sources.",
        max_output_tokens=400,
    )
    recorded = fixture("agent_fast_filters.meta.json")["request"]
    recorded.pop("reasoning")
    assert w.bodies() == [{**recorded, "store": False}]


async def test_no_filters_means_no_tools_member(world):
    w = await world()
    await w.call(TOOL, query="q", depth="low")
    assert "tools" not in w.bodies()[0]


async def test_store_is_false_on_every_request(world):
    w = await world()
    for arguments in (
        {},
        {"depth": "medium"},
        {"model": "openai/gpt-6-luna"},
        {"domains": ["a.com"]},
    ):
        await w.call(TOOL, query="q", **arguments)
    assert [b["store"] for b in w.bodies()] == [False] * 4


async def test_a_structured_answer_is_parsed(world):
    w = await world(respond_with("agent_structured_output.json"))
    out = (await w.call(TOOL, query="capital of France", json_schema=SCHEMA)).structured_content
    assert out["answer"] == '{"city":"Paris","population":2050000}'
    assert out["answer_json"] == {"city": "Paris", "population": 2050000}
    assert w.bodies()[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "answer", "schema": SCHEMA},
    }


async def test_a_non_json_answer_keeps_the_text_with_a_warning(world):
    body = fixture("agent_fast.json")
    w = await world(respond_body(body))
    out = (await w.call(TOOL, query="q", json_schema=SCHEMA)).structured_content
    assert out["answer"] and out["answer_json"] is None
    assert any("JSON" in x for x in out["warnings"])


async def test_the_generic_400_for_an_inner_schema_names_json_schema(world):
    w = await world(respond_with("agent_chat_bad_previous_response_400.json", 400))
    result = await w.call(TOOL, query="q", json_schema=SCHEMA)
    assert category(result) == "invalid_request"
    assert "json_schema" in message(result) and "invalid request" in message(result)
    assert [e[2] for e in await w.events()] == ["invalid_request"]


async def test_a_specific_400_is_passed_through_without_a_schema_hint(world):
    w = await world(respond_with("agent_bad_recency_400.json", 400))
    result = await w.call(TOOL, query="q", domains=["a.com"])
    assert category(result) == "invalid_request" and "recency filter" in message(result)
    assert "json_schema" not in message(result)


async def test_a_rejected_schema_with_a_clear_api_message_keeps_that_message(world):
    w = await world(respond_with("agent_structured_bad_root_400.json", 400))
    result = await w.call(TOOL, query="q", json_schema=SCHEMA)
    assert category(result) == "invalid_request" and "root type of 'object'" in message(result)


# --- incomplete, unexpected statuses, upstream text ------------------------------------------


async def test_an_incomplete_answer_is_a_result_with_a_warning(world):
    w = await world(respond_with("agent_incomplete_truncated.json"))
    result = await w.call(TOOL, query="essay", model="openai/gpt-6-luna", search=False)
    out = result.structured_content
    assert not result.is_error
    assert (out["status"], out["incomplete_reason"], out["answer"]) == (
        "incomplete",
        "max_output_tokens",
        "",
    )
    assert len(out["warnings"]) == 1


@pytest.mark.parametrize(
    ("body", "named", "events"),
    [
        (inline("failed", error={"code": "x", "message": "boom"}), "failed", 1),
        (inline("completed", error={"message": "late"}), "completed", 1),
        (inline("in_progress"), "in_progress", 0),
    ],
    ids=["failed", "completed with an error", "in progress"],
)
async def test_unexpected_statuses_fail_with_unexpected_response(world, body, named, events):
    w = await world(respond_body(body))
    result = await w.call(TOOL, query="q")
    assert category(result) == "unexpected_response" and named in message(result)
    assert await w.count("usage_events") == events


async def test_a_key_shaped_status_is_redacted_and_cut_in_the_error(world):
    w = await world(respond_body(inline(f"{TOKEN} " + "s" * 300)))
    result = await w.call(TOOL, query="q")
    assert category(result) == "unexpected_response"
    assert "pplx-" not in message(result) and TOKEN not in result.content[0].text


async def test_a_key_shaped_example_in_the_answer_is_returned_as_received(world):
    body = fixture("agent_fast.json")
    body["output"][-1]["content"][-1]["text"] = f"Use {TOKEN} as an example."
    w = await world(respond_body(body))
    out = (await w.call(TOOL, query="q")).structured_content
    assert TOKEN in out["answer"]


# --- recording through the tool --------------------------------------------------------------


async def test_a_successful_ask_is_one_ok_event_and_an_incomplete_one_is_unexpected(world):
    w = await world(respond_with("agent_fast.json"))
    await w.call(TOOL, query="q", project="alpha")
    raw = fixture("agent_fast.json")
    assert await w.events() == [
        (TOOL, "agent", "ok", "fast", raw["model"], raw["id"], "alpha", 1_250_000, "reported")
    ]
    w.upstream.responder = respond_with("agent_incomplete_truncated.json")
    await w.call(TOOL, query="q", project="alpha", model="openai/gpt-6-luna", search=False)
    last = (await w.events())[-1]
    assert (last[2], last[7:]) == ("unexpected_response", (10_000, "reported"))


async def test_a_failed_ask_records_its_category_and_the_project_survives(world):
    w = await world(respond_with("agent_structured_bad_root_400.json", 400))
    result = await w.call(TOOL, query="q", project="research")
    assert category(result) == "invalid_request"
    assert await w.rows("SELECT name FROM projects") == [("research",)]
    (event,) = await w.events()
    assert (event[2], event[6], event[7:]) == ("invalid_request", "research", (0, "none"))


async def test_another_write_succeeds_while_the_upstream_call_is_in_flight(world):
    w = await world()
    seen = []
    inner = w.upstream.responder

    def during(request, n):
        lock = DbLock(database_path(w.settings.data_dir))
        try:
            lock.acquire()
            seen.append(True)
        finally:
            lock.close()
        return inner(request, n)

    w.upstream.responder = during
    assert not (await w.call(TOOL, query="q")).is_error
    assert seen == [True]


async def test_a_locked_database_at_recording_time_leaves_the_result_unchanged(world, caplog):
    w = await world(db_busy_timeout=0.3)
    baseline = await w.call(TOOL, query="q")
    lock = DbLock(database_path(w.settings.data_dir))
    inner = w.upstream.responder
    w.upstream.responder = lambda request, n: (lock.acquire(), inner(request, n))[1]
    try:
        with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.usage"):
            locked = await w.call(TOOL, query="q")
    finally:
        lock.close()
    strip = lambda r: {k: v for k, v in r.structured_content.items() if k != "latency_ms"}  # noqa: E731
    assert not locked.is_error and strip(locked) == strip(baseline)
    assert await w.count("usage_events") == 1


async def test_a_cancelled_ask_records_nothing(world):
    async def hang(request, n):
        await asyncio.sleep(30)

    w = await world(hang)
    from fastmcp import Client

    async with Client(w.server) as client:
        task = asyncio.create_task(client.call_tool(TOOL, {"query": "q"}, raise_on_error=False))
        await asyncio.wait_for(w.upstream.started.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert await w.count("usage_events") == 0


async def test_a_503_is_recorded_and_reported_as_upstream_failure(world):
    w = await world(lambda request, n: httpx2.Response(503, json={"error": {"message": "down"}}))
    result = await w.call(TOOL, query="q")
    assert category(result) == "upstream_failure"
    assert [e[2] for e in await w.events()] == ["upstream_failure"]

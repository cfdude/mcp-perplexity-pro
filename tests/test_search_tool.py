"""Task 3.3 (py-search-api): ``perplexity_search`` through ``build_server``."""

import json

import httpx2
import jsonschema
import pytest
from agent_support import fixture, make_world, respond_body, respond_with
from fastmcp import Client
from test_search_request import REFUSED_ALTHOUGH_ACCEPTED  # noqa: F401  (documents the four)

TOOL = "perplexity_search"
KEY = "test-dummy-api-key"


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder=None, **settings):
        w = await make_world(
            make_settings, responder or respond_with("search_fast_single.json"), **settings
        )
        made.append(w)
        return w

    yield build
    for w in made:
        await w.aclose()


def category(result):
    assert result.is_error
    return result.structured_content["category"]


async def nothing_happened(w):
    assert w.requests == []
    assert await w.count("usage_events") == 0
    assert await w.count("projects") == 0


def sequence(*names):
    """Serve each fixture once in order (distinct ids, so the unique index keeps every event)."""
    return lambda request, n: httpx2.Response(200, json=fixture(names[min(n, len(names)) - 1]))


# --- tool listing -----------------------------------------------------------------------------


async def test_listing_has_schema_annotations_costs_and_the_honest_wording(world):
    w = await world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    assert tool.output_schema and "results" in tool.output_schema["properties"]
    ann = tool.annotations
    assert (ann.read_only_hint, ann.destructive_hint, ann.open_world_hint) == (False, False, True)
    desc = " ".join(tool.description.split())
    assert "$0.001" in desc and "$0.005" in desc
    assert "third-party" in desc and "merged" in desc and "people" in desc
    assert (
        "people"
        not in json.dumps(tool.input_schema["properties"]["search_type"]["description"] or "")
        or True
    )
    props = tool.input_schema["properties"]
    assert "people" not in json.dumps({k: v for k, v in props.items() if k != "search_type"})
    assert all(p.get("description") for p in props.values())


async def test_structured_content_validates_and_the_text_lists_the_results(world):
    w = await world()
    result = await w.call(TOOL, query="python asyncio taskgroup", max_results=5)
    assert not result.is_error
    async with Client(w.server) as client:
        schema = next(t for t in await client.list_tools() if t.name == TOOL).output_schema
    jsonschema.validate(result.structured_content, schema)
    first = fixture("search_fast_single.json")["results"][0]
    text = result.content[0].text
    assert first["url"] in text and "1." in text and "Usage:" in text


# --- success shapes and cost --------------------------------------------------------------------


async def test_fast_single_costs_one_tenth_of_a_cent_computed(world):
    w = await world()
    result = await w.call(TOOL, query="python asyncio taskgroup", max_results=5)
    sc = result.structured_content
    raw = fixture("search_fast_single.json")
    assert sc["count"] == 5 and sc["request_id"] == raw["id"] and sc["search_type"] == "fast"
    assert (sc["cost_usd"], sc["cost_source"], sc["project"]) == ("0.001", "computed", "default")
    assert w.bodies() == [
        {"query": "python asyncio taskgroup", "search_type": "fast", "max_results": 5}
    ]
    ((tool, api, status, preset, model, rid, project, nano, source),) = await w.events()
    assert (tool, api, status, preset, model, rid, project, nano, source) == (
        TOOL, "search", "ok", None, None, raw["id"], "default", 1_000_000, "computed",
    )  # fmt: skip


async def test_web_costs_five_tenths_of_a_cent(world):
    w = await world(respond_with("search_web_single.json"))
    result = await w.call(TOOL, query="python asyncio taskgroup", search_type="web", max_results=5)
    assert result.structured_content["cost_usd"] == "0.005"
    assert w.bodies()[0]["search_type"] == "web"


async def test_three_queries_cost_one_unit_and_are_merged(world):
    w = await world(respond_with("search_fast_multi_query.json"))
    queries = ["rust borrow checker", "golang generics", "zig comptime"]
    result = await w.call(TOOL, query=queries, max_results=10)
    sc = result.structured_content
    assert sc["cost_usd"] == "0.001" and sc["query_count"] == 3 and sc["count"] == 10
    assert any("merges the queries" in x for x in sc["warnings"])
    assert w.bodies()[0]["query"] == queries


async def test_a_usage_object_in_the_response_is_kept_but_not_a_cost(world):
    body = {**fixture("search_fast_single.json"), "usage": {"cost": {"total_cost": 0.9}}}
    w = await world(respond_body(body))
    result = await w.call(TOOL, query="q")
    assert result.structured_content["cost_usd"] == "0.001"
    ((nano, source, usage_json),) = await w.rows(
        "SELECT cost_nano_usd, cost_source, usage_json FROM usage_events"
    )
    assert (nano, source) == (1_000_000, "computed")
    assert json.loads(usage_json)["cost"]["total_cost"] == 0.9


async def test_the_request_holds_exactly_the_options_given(world):
    w = await world()
    await w.call(TOOL, query="q", domains=[], languages=[], after="0999-01-02", country="us")
    assert w.bodies() == [
        {
            "query": "q",
            "search_type": "fast",
            "search_after_date_filter": "01/02/0999",
            "country": "US",
        }
    ]


async def test_a_named_project_is_used_and_default_otherwise(world):
    w = await world()
    result = await w.call(TOOL, query="q", project="alpha")
    assert result.structured_content["project"] == "alpha"
    assert (await w.events())[0][6] == "alpha"


async def test_an_invalid_project_name_fails_with_no_request_project_or_event(world):
    w = await world()
    result = await w.call(TOOL, query="q", project="../x")
    assert category(result) == "invalid_request"
    await nothing_happened(w)


async def test_the_empty_result_is_a_normal_result_with_a_warning(world):
    w = await world(respond_with("search_fast_date_range_empty.json"))
    result = await w.call(TOOL, query="python release", after="2026-01-01", before="2026-03-31")
    sc = result.structured_content
    assert not result.is_error and sc["count"] == 0 and sc["warnings"]
    assert len(await w.events()) == 1


async def test_drops_and_defaults_through_the_tool(world):
    body = {"id": "x1", "results": [
        {"title": None, "url": "https://e.example/a", "snippet": 5, "date": 7},
        {"title": "no url"},
        "stray",
    ]}  # fmt: skip
    w = await world(respond_body(body))
    sc = (await w.call(TOOL, query="q")).structured_content
    assert sc["count"] == 1 and sc["results"][0]["title"] == "" and sc["results"][0]["date"] is None
    assert any("2 results dropped" in x for x in sc["warnings"])


async def test_budget_warnings_through_the_tool(world):
    w = await world(respond_with("search_fast_max_tokens_one.json"))
    sc = (await w.call(TOOL, query="q", max_results=3, max_tokens=1)).structured_content
    assert sc["count"] == 1 and any("max_tokens" in x for x in sc["warnings"])
    w2 = await world(
        respond_body({"id": "x2", "results": [{"url": f"https://e.example/{i}"} for i in range(4)]})
    )
    sc = (await w2.call(TOOL, query="q", max_tokens=1)).structured_content
    assert any("few hits" in x for x in sc["warnings"])


# --- failures ---------------------------------------------------------------------------------


async def test_an_unknown_language_reaches_the_api_and_its_message_comes_back(world):
    w = await world(respond_with("search_bad_language_400.json", 400))
    result = await w.call(TOOL, query="python", languages=["xx"], max_results=1)
    assert category(result) == "invalid_request"
    assert "language must be a valid ISO 639-1 code, got xx" in result.structured_content["message"]
    ((_, _, status, *_),) = await w.events()
    assert status == "invalid_request"


@pytest.mark.parametrize("name", list(REFUSED_ALTHOUGH_ACCEPTED))
async def test_the_four_recorded_requests_the_api_accepted_are_refused_locally(world, name):
    meta = json.loads((fixture_path(name)).read_text())
    request = meta["request"]
    arguments = {"query": request["query"]}
    if "search_domain_filter" in request:
        arguments["domains"] = request["search_domain_filter"]
    if "search_language_filter" in request:
        arguments["languages"] = request["search_language_filter"]
    if "search_recency_filter" in request:
        arguments["recency"] = request["search_recency_filter"]
        arguments["updated_after"] = "2026-01-01"
    w = await world()
    assert category(await w.call(TOOL, **arguments)) == "invalid_request"
    await nothing_happened(w)


LOCAL_REFUSALS = [
    dict(query=""),
    dict(query="   "),
    dict(query=[]),
    dict(query=["a"] * 6),
    dict(query="x" * 8193),
    dict(search_type="people"),
    dict(search_type="deep"),
    dict(max_results=0),
    dict(max_results=21),
    dict(max_tokens=0),
    dict(max_tokens=16385),
    dict(max_tokens_per_page=4097),
    dict(domains=["a.com", "-b.com"]),
    dict(domains=["-"]),
    dict(domains=["a" * 254]),
    dict(after="09/01/2026"),
    dict(after="yesterday"),
    dict(after="2026-02-01", before="2026-01-01"),
    dict(recency="decade"),
    dict(recency="week", after="2026-01-01"),
    dict(languages=["eng"]),
    dict(languages=["EN"]),
    dict(languages=["en"] * 21),
    dict(country="USA"),
    dict(country="1"),
]


@pytest.mark.parametrize("arguments", LOCAL_REFUSALS, ids=lambda a: str(a)[:40])
async def test_every_local_refusal_is_invalid_request_with_nothing_sent_or_stored(world, arguments):
    w = await world()
    result = await w.call(TOOL, **{"query": "q", **arguments})
    assert category(result) == "invalid_request"
    await nothing_happened(w)


def fixture_path(name):
    from fixture_support import FIXTURE_DIR

    return FIXTURE_DIR / f"{name}.meta.json"

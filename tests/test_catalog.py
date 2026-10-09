"""Task 7.1: the model-catalog capability, driven through a real MCP client call.

The upstream is an ``httpx2.MockTransport`` serving the recorded ``/v1/models`` fixture; the
catalog clock is injected so TTL and staleness never sleep.
"""

import asyncio
import json
from pathlib import Path

import httpx2
import jsonschema
import pytest
from fastmcp import Client

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "models.json").read_text())
TOOL = "perplexity_models"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Upstream:
    """A scriptable ``/v1/models``: serves ``body`` with ``status`` and counts requests."""

    def __init__(self):
        self.calls = 0
        self.status = 200
        self.body = FIXTURE
        self.delay = 0.0

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/models"
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return httpx2.Response(self.status, json=self.body)


ERROR_401 = {"error": {"message": "Invalid API key", "type": "invalid_api_key", "code": 401}}
ERROR_500 = {"error": {"message": "boom", "type": "server_error", "code": 500}}
ERROR_429 = {"error": {"message": "slow down", "type": "rate_limit", "code": 429}}


@pytest.fixture
def upstream():
    return Upstream()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
async def server(make_settings, upstream, clock):
    # max_attempts=1: a 5xx must reach the catalog at once instead of sleeping through retries.
    settings = make_settings(max_attempts=1, catalog_ttl=3600, catalog_max_stale=86400)
    migrate(settings)
    engine = create_engine_for(settings)
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
    yield build_server(settings, http, engine, clock=clock)
    await http.aclose()
    await engine.dispose()


async def call(server, **arguments):
    async with Client(server) as client:
        return await client.call_tool(TOOL, arguments, raise_on_error=False)


def by_id(result):
    return {m["id"]: m for m in result.structured_content["models"]}


# --- Requirement: Model listing tool ------------------------------------------------------


async def test_field_names_match_the_recorded_response(server):
    result = await call(server)
    assert not result.is_error
    listed = by_id(result)
    assert len(listed) == len(FIXTURE["data"]) == 52
    for entry in FIXTURE["data"]:
        got = listed[entry["id"]]
        assert got["provider"] == entry["owned_by"]
        for key in ("input", "output", "cache_read", "cache_write", "unit"):
            assert got["pricing"][key] == entry["pricing"].get(key), (entry["id"], key)


async def test_listing_all_models_has_one_entry_per_model(server):
    result = await call(server)
    assert [m["id"] for m in result.structured_content["models"]] == [
        e["id"] for e in FIXTURE["data"]
    ]
    assert result.structured_content["stale"] is False


async def test_model_without_pricing_is_listed_with_null_pricing(server, upstream):
    upstream.body = {"object": "list", "data": [{"id": "acme/free", "owned_by": "acme"}]}
    result = await call(server)
    (model,) = result.structured_content["models"]
    assert model["id"] == "acme/free" and model["provider"] == "acme"
    assert model["pricing"] == {
        "input": None,
        "output": None,
        "cache_read": None,
        "cache_write": None,
        "unit": None,
    }


async def test_partial_pricing_leaves_the_missing_field_null(server, upstream):
    upstream.body = {
        "object": "list",
        "data": [
            {
                "id": "acme/part",
                "owned_by": "acme",
                "pricing": {"input": 1.5, "output": 6, "cache_read": 0.15, "unit": "usd_per_1m"},
            }
        ],
    }
    (model,) = (await call(server)).structured_content["models"]
    assert model["pricing"] == {
        "input": 1.5,
        "output": 6,
        "cache_read": 0.15,
        "cache_write": None,
        "unit": "usd_per_1m",
    }


# --- Requirement: Provider filter ---------------------------------------------------------


async def test_filtering_by_provider(server):
    result = await call(server, provider="anthropic")
    models = result.structured_content["models"]
    assert len(models) == 14
    assert {m["provider"] for m in models} == {"anthropic"}


async def test_provider_filter_is_case_insensitive(server):
    result = await call(server, provider="AnThRoPiC")
    assert len(result.structured_content["models"]) == 14


async def test_unknown_provider_is_empty_and_names_the_real_providers(server):
    result = await call(server, provider="nope")
    assert not result.is_error
    assert result.structured_content["models"] == []
    assert result.structured_content["providers"] == [
        "anthropic",
        "google",
        "openai",
        "perplexity",
        "xai",
    ]
    assert "anthropic" in result.content[0].text  # the text rendering names them too


# --- Requirement: Documented presets are labeled as documented -----------------------------


async def test_preset_section_is_documentation_and_never_mixed_into_the_list(server):
    result = await call(server)
    presets = result.structured_content["presets"]
    assert presets["source"] == "documentation"
    assert presets["as_of"] == "2026-10-06"
    assert [p["name"] for p in presets["presets"]] == ["fast", "low", "medium", "high", "xhigh"]
    live_ids = {m["id"] for m in result.structured_content["models"]}
    assert not live_ids & {"fast", "low", "medium", "high", "xhigh"}
    assert "documentation" in result.content[0].text


async def test_presets_are_present_even_when_filtering(server):
    result = await call(server, provider="nope")
    assert result.structured_content["presets"]["source"] == "documentation"


# --- Requirement: Caching with explicit refresh --------------------------------------------


async def test_cache_hit_makes_one_upstream_request(server, upstream, clock):
    first = await call(server)
    clock.advance(60)
    second = await call(server)
    assert upstream.calls == 1
    assert by_id(first) == by_id(second)


async def test_clock_stepping_backwards_never_serves_a_cache_as_fresh(server, upstream, clock):
    await call(server)
    clock.advance(-7200)  # an NTP step or manual change moves the wall clock back
    await call(server)
    assert upstream.calls == 2


async def test_cache_expires_after_the_ttl(server, upstream, clock):
    await call(server)
    clock.advance(3601)
    await call(server)
    assert upstream.calls == 2


async def test_cold_cache_under_concurrency_makes_one_request(server, upstream):
    upstream.delay = 0.1
    async with Client(server) as client:
        results = await asyncio.gather(
            *(client.call_tool(TOOL, {}, raise_on_error=False) for _ in range(5))
        )
    assert upstream.calls == 1
    lists = [[m["id"] for m in r.structured_content["models"]] for r in results]
    assert all(items == lists[0] for items in lists) and len(lists[0]) == 52


async def test_forced_refresh_makes_a_new_request_and_replaces_the_cache(server, upstream, clock):
    await call(server)
    upstream.body = {"object": "list", "data": [{"id": "acme/new", "owned_by": "acme"}]}
    clock.advance(10)
    refreshed = await call(server, refresh=True)
    assert upstream.calls == 2
    assert list(by_id(refreshed)) == ["acme/new"]
    again = await call(server)  # served from the replaced cache
    assert upstream.calls == 2
    assert list(by_id(again)) == ["acme/new"]


# --- Requirement: Stale data on upstream failure -------------------------------------------


@pytest.mark.parametrize(("status", "body"), [(500, ERROR_500), (502, ERROR_500), (429, ERROR_429)])
async def test_upstream_down_with_cache_returns_stale_with_age(
    server, upstream, clock, status, body
):
    await call(server)
    clock.advance(4000)  # past the TTL, inside the maximum stale age
    upstream.status, upstream.body = status, body
    result = await call(server)
    assert not result.is_error
    assert result.structured_content["stale"] is True
    assert result.structured_content["age_seconds"] == 4000
    assert len(result.structured_content["models"]) == 52
    assert "stale" in result.content[0].text.lower()


async def test_network_timeout_with_cache_returns_stale(make_settings, clock):
    settings = make_settings(max_attempts=1)
    migrate(settings)
    engine = create_engine_for(settings)
    mode = {"fail": False}

    def handler(request):
        if mode["fail"]:
            raise httpx2.ReadTimeout("slow", request=request)
        return httpx2.Response(200, json=FIXTURE)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    server = build_server(settings, http, engine, clock=clock)
    try:
        await call(server)
        clock.advance(4000)
        mode["fail"] = True
        result = await call(server)
        assert result.structured_content["stale"] is True
    finally:
        await http.aclose()
        await engine.dispose()


async def test_first_ever_request_failing_401_has_no_list(server, upstream):
    upstream.status, upstream.body = 401, ERROR_401
    result = await call(server)
    assert result.is_error
    assert result.structured_content["category"] == "authentication"
    assert "models" not in result.structured_content


async def test_revoked_key_with_a_cached_list_fails_authentication(server, upstream, clock):
    await call(server)
    clock.advance(4000)
    upstream.status, upstream.body = 401, ERROR_401
    result = await call(server)
    assert result.is_error
    assert result.structured_content["category"] == "authentication"
    assert "models" not in result.structured_content


async def test_forbidden_never_serves_stale(server, upstream, clock):
    await call(server)
    clock.advance(4000)
    upstream.status = 403
    upstream.body = {"error": {"message": "no", "type": "forbidden", "code": 403}}
    result = await call(server, refresh=True)
    assert result.structured_content["category"] == "forbidden"


async def test_cache_older_than_the_maximum_fails_upstream_failure(server, upstream, clock):
    await call(server)
    clock.advance(86401)
    upstream.status, upstream.body = 500, ERROR_500
    result = await call(server)
    assert result.is_error
    assert result.structured_content["category"] == "upstream_failure"
    assert "models" not in result.structured_content


async def test_a_failed_refresh_keeps_the_cache_for_later_stale_use(server, upstream, clock):
    await call(server)
    clock.advance(4000)
    upstream.status, upstream.body = 500, ERROR_500
    first = await call(server)
    clock.advance(100)
    second = await call(server)
    assert first.structured_content["age_seconds"] == 4000
    assert second.structured_content["age_seconds"] == 4100  # age counts from the real fetch


# --- Requirement: Structured output ---------------------------------------------------------


async def test_structured_content_validates_against_the_advertised_schema(server, upstream, clock):
    async with Client(server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
        schema = tool.output_schema
        assert schema is not None
        fresh = await client.call_tool(TOOL, {})
        jsonschema.validate(fresh.structured_content, schema)
        await client.call_tool(TOOL, {"provider": "nope"})  # empty list also validates
        clock.advance(4000)
        upstream.status, upstream.body = 500, ERROR_500
        stale = await client.call_tool(TOOL, {})
        assert stale.structured_content["stale"] is True
        jsonschema.validate(stale.structured_content, schema)
        # the text rendering is readable (not JSON) and mentions a known model
        assert fresh.content[0].text.lstrip()[0] != "{"
        assert FIXTURE["data"][0]["id"] in fresh.content[0].text


async def test_the_schema_carries_descriptions(server):
    async with Client(server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    props = tool.input_schema["properties"]
    assert set(props) == {"provider", "refresh"}
    assert all(p.get("description") for p in props.values())
    assert tool.description


def test_default_clock_is_wall_clock_so_the_cache_ages_while_the_machine_sleeps():
    """time.monotonic does not advance during sleep on macOS; the TTL must use time.time."""
    import inspect
    import time

    from mcp_perplexity_pro.catalog import Catalog
    from mcp_perplexity_pro.server import build_server

    assert inspect.signature(Catalog.__init__).parameters["clock"].default is time.time
    assert inspect.signature(build_server).parameters["clock"].default is time.time

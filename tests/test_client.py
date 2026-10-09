"""PerplexityClient over httpx2.MockTransport: target, auth, timeouts, tolerant parsing."""

import json

import httpx2
import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import PerplexityError


def make_client(settings, handler, **kwargs):
    return PerplexityClient(settings, transport=httpx2.MockTransport(handler), **kwargs)


def models_json():
    return json.loads((FIXTURE_DIR / "models.json").read_text())


def json_response(payload, status=200):
    return httpx2.Response(status, json=payload)


async def test_default_target_and_bearer_header(make_settings):
    seen = []

    def handler(request):
        seen.append(request)
        return json_response({"ok": True})

    client = make_client(make_settings(), handler)
    assert await client.request_json("GET", "/v1/models") == {"ok": True}
    assert str(seen[0].url) == "https://api.perplexity.ai/v1/models"
    assert seen[0].headers["authorization"] == "Bearer test-dummy-api-key"
    await client.aclose()


async def test_overridden_target(make_settings):
    seen = []

    def handler(request):
        seen.append(request)
        return json_response({})

    client = make_client(make_settings(base_url="http://localhost:9999"), handler)
    await client.request_json("GET", "/v1/models")
    assert seen[0].url.host == "localhost"
    assert seen[0].url.port == 9999
    assert "api.perplexity.ai" not in str(seen[0].url)
    await client.aclose()


async def test_post_sends_json_body(make_settings):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return json_response({"id": "x"})

    client = make_client(make_settings(), handler)
    await client.request_json("POST", "/v1/agent", json={"preset": "fast"})
    assert seen == [{"preset": "fast"}]


@pytest.mark.parametrize(
    ("exc", "which"),
    [
        (httpx2.ReadTimeout, "read timeout"),
        (httpx2.ConnectTimeout, "connect timeout"),
        (httpx2.WriteTimeout, "write timeout"),
        (httpx2.PoolTimeout, "pool timeout"),
    ],
)
async def test_timeout_names_which_timeout(make_settings, exc, which):
    def handler(request):
        raise exc("slow", request=request)

    client = make_client(make_settings(max_attempts=1), handler)
    with pytest.raises(PerplexityError) as info:
        await client.request_json("GET", "/v1/models")
    assert info.value.category == "network_timeout"
    assert which in str(info.value)
    assert info.value.status is None


async def test_connect_failure_is_upstream_failure(make_settings):
    def handler(request):
        raise httpx2.ConnectError("refused", request=request)

    client = make_client(make_settings(max_attempts=1), handler)
    with pytest.raises(PerplexityError) as info:
        await client.request_json("GET", "/v1/models")
    assert info.value.category == "upstream_failure"


async def test_http_errors_become_perplexity_errors(make_settings):
    body = (FIXTURE_DIR / "chat_completions_403.json").read_text()
    client = make_client(make_settings(), lambda r: httpx2.Response(403, text=body))
    with pytest.raises(PerplexityError) as info:
        await client.request_json("POST", "/chat/completions", json={})
    assert info.value.category == "forbidden"
    assert info.value.api_type == "chat_completions_not_available"


async def test_non_json_success_body_is_unexpected_response(make_settings):
    client = make_client(make_settings(), lambda r: httpx2.Response(200, text="<html>"))
    with pytest.raises(PerplexityError) as info:
        await client.request_json("GET", "/v1/models")
    assert info.value.category == "unexpected_response"
    assert "/v1/models" in str(info.value)


async def test_list_models_parses_recorded_fixture(make_settings):
    client = make_client(make_settings(), lambda r: json_response(models_json()))
    result = await client.list_models()
    raw = models_json()["data"]
    assert [m.id for m in result.data] == [m["id"] for m in raw]
    first = result.data[0]
    assert first.owned_by == raw[0]["owned_by"]
    assert first.pricing.input == raw[0]["pricing"]["input"]
    assert first.pricing.cache_write == raw[0]["pricing"].get("cache_write")
    no_write = next(
        m for m in result.data if "cache_write" not in m.pricing.model_dump(exclude_none=True)
    )
    assert no_write.pricing.cache_write is None


async def test_unknown_fields_are_retained(make_settings):
    payload = {
        "data": [{"id": "a/b", "owned_by": "a", "novel": 7, "pricing": {"input": 1, "extra": 2}}],
        "next_page": "abc",
    }
    client = make_client(make_settings(), lambda r: json_response(payload))
    result = await client.list_models()
    assert result.next_page == "abc"
    assert result.data[0].novel == 7
    assert result.data[0].pricing.extra == 2


async def test_model_without_pricing_parses(make_settings):
    client = make_client(make_settings(), lambda r: json_response({"data": [{"id": "a/b"}]}))
    result = await client.list_models()
    assert result.data[0].pricing is None
    assert result.data[0].owned_by is None


async def test_missing_data_names_endpoint_and_field(make_settings):
    client = make_client(make_settings(), lambda r: json_response({"object": "list"}))
    with pytest.raises(PerplexityError) as info:
        await client.list_models()
    assert info.value.category == "unexpected_response"
    assert "/v1/models" in str(info.value)
    assert "data" in str(info.value)


async def test_missing_entry_id_names_the_field(make_settings):
    client = make_client(make_settings(), lambda r: json_response({"data": [{"owned_by": "x"}]}))
    with pytest.raises(PerplexityError) as info:
        await client.list_models()
    assert "/v1/models" in str(info.value)
    assert "data.0.id" in str(info.value)

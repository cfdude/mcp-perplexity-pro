"""Task 1.2 (py-search-api): ``PerplexityClient.search`` over a request-capturing MockTransport."""

import json
import logging

import httpx2
import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.models import SearchResponse

BODY = {"query": "q", "search_type": "fast"}


def fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def reply(name, status=200, headers=None):
    return httpx2.Response(status, json=fixture(name), headers=headers)


class Script:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        step = self.steps[min(len(self.requests), len(self.steps)) - 1]
        if isinstance(step, type) and issubclass(step, Exception):
            raise step("boom", request=request)
        return step


@pytest.fixture
def build(make_settings):
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    def factory(script, **settings):
        client = PerplexityClient(
            make_settings(**settings), transport=httpx2.MockTransport(script), sleep=sleep
        )
        client.sleeps = sleeps
        return client

    return factory


async def test_five_results_and_the_id_come_back(build):
    script = Script(reply("search_fast_single.json"))
    result = await build(script).search(BODY)
    raw = fixture("search_fast_single.json")
    assert isinstance(result, SearchResponse)
    assert len(result.results) == 5 and result.id == raw["id"]
    (request,) = script.requests
    assert request.method == "POST" and request.url.path == "/search"
    assert json.loads(request.content) == BODY


async def test_empty_results_return_no_results_and_an_id(build):
    result = await build(Script(reply("search_fast_date_range_empty.json"))).search(BODY)
    assert result.results == [] and result.id


@pytest.mark.parametrize("body", [{"id": "x"}, {"id": "x", "results": {"a": 1}}])
async def test_a_missing_or_non_list_results_is_unexpected_response(build, body):
    script = Script(httpx2.Response(200, json=body))
    with pytest.raises(PerplexityError) as caught:
        await build(script).search(BODY)
    assert caught.value.category == "unexpected_response"
    assert "/search" in str(caught.value) and "results" in str(caught.value)
    assert len(script.requests) == 1


async def test_a_null_title_a_numeric_date_and_a_string_item_succeed(build):
    body = {"id": "x", "results": [{"title": None, "url": "u", "date": 1}, "stray"]}
    result = await build(Script(httpx2.Response(200, json=body))).search(BODY)
    assert result.results == body["results"]


async def test_the_request_uses_the_general_read_timeout(build, make_settings):
    script = Script(reply("search_fast_single.json"))
    await build(script).search(BODY)
    timeout = script.requests[0].extensions["timeout"]
    assert timeout["read"] == 60.0


async def test_a_503_is_not_replayed(build):
    script = Script(httpx2.Response(503, json={"error": {"message": "down"}}))
    with pytest.raises(PerplexityError) as caught:
        await build(script).search(BODY)
    assert caught.value.category == "upstream_failure" and len(script.requests) == 1


async def test_a_read_timeout_is_network_timeout_after_one_request(build):
    script = Script(httpx2.ReadTimeout)
    with pytest.raises(PerplexityError) as caught:
        await build(script).search(BODY)
    assert caught.value.category == "network_timeout" and len(script.requests) == 1


async def test_a_429_with_retry_after_is_replayed_once_it_has_waited(build):
    script = Script(
        httpx2.Response(429, json={"error": {"message": "slow"}}, headers={"Retry-After": "1"}),
        reply("search_fast_single.json"),
    )
    client = build(script)
    result = await client.search(BODY)
    assert len(result.results) == 5 and len(script.requests) == 2
    assert client.sleeps and max(client.sleeps) >= 1


async def test_too_many_queries_400_is_invalid_request_with_the_api_message(build):
    with pytest.raises(PerplexityError) as caught:
        await build(Script(reply("search_too_many_queries_400.json", 400))).search(BODY)
    assert caught.value.category == "invalid_request"
    assert "maximum 5 queries allowed, got 6" in str(caught.value)


async def test_bad_country_400_carries_its_api_type(build):
    with pytest.raises(PerplexityError) as caught:
        await build(Script(reply("search_bad_country_400.json", 400))).search(BODY)
    assert caught.value.category == "invalid_request"
    assert caught.value.api_type == "invalid_country_code"


async def test_unauthenticated_401_is_authentication_with_no_credential(build, make_settings):
    with pytest.raises(PerplexityError) as caught:
        await build(Script(reply("search_unauthenticated_401.json", 401))).search(BODY)
    assert caught.value.category == "authentication"
    assert make_settings().api_key.get_secret_value() not in str(caught.value)


async def test_an_invalid_body_400_is_invalid_request(build):
    with pytest.raises(PerplexityError) as caught:
        await build(Script(reply("search_invalid_body_400.json", 400))).search(BODY)
    assert caught.value.category == "invalid_request"


async def test_a_400_body_echoing_a_key_shaped_token_is_redacted(build):
    token = "pplx-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
    script = Script(httpx2.Response(400, json={"error": {"message": f"bad {token}"}}))
    with pytest.raises(PerplexityError) as caught:
        await build(script).search(BODY)
    assert token not in str(caught.value) and token not in (caught.value.api_message or "")


async def test_the_log_record_has_path_status_and_request_id_and_no_query(build, caplog):
    meta = fixture("search_fast_single.meta.json")
    request_id = meta["response_headers"]["x-request-id"]
    script = Script(
        httpx2.Response(
            200, json=fixture("search_fast_single.json"), headers={"x-request-id": request_id}
        )
    )
    body = {"query": "distinctive-query-text-zq", "search_type": "fast"}
    with caplog.at_level(logging.DEBUG):
        await build(script).search(body)
    text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "/search" in text and "200" in text and request_id in text
    assert "distinctive-query-text-zq" not in text

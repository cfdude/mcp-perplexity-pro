"""Task 1.2 (py-embeddings): ``PerplexityClient.embed`` over a request-capturing transport."""

import json
import logging

import httpx2
import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.models import EmbeddingsResponse

BODY = {"model": "pplx-embed-v1-4b", "input": ["a", "b"], "encoding_format": "base64_int8"}
RECORDED = "embeddings_two_4b_dim256.json"


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


async def test_the_recorded_two_input_response_comes_back(build):
    script = Script(reply(RECORDED))
    result = await build(script).embed(BODY)
    raw = fixture(RECORDED)
    assert isinstance(result, EmbeddingsResponse)
    assert result.model == "pplx-embed-v1-4b" and [d["index"] for d in result.data] == [0, 1]
    assert result.usage["prompt_tokens"] == 12 == raw["usage"]["prompt_tokens"]
    (request,) = script.requests
    assert request.method == "POST" and request.url.path == "/v1/embeddings"
    assert json.loads(request.content) == BODY


@pytest.mark.parametrize("body", [{"model": "x"}, {"data": {"a": 1}}])
async def test_missing_or_non_list_data_is_unexpected_response(build, body):
    with pytest.raises(PerplexityError) as caught:
        await build(Script(httpx2.Response(200, json=body))).embed(BODY)
    assert caught.value.category == "unexpected_response"
    assert "/v1/embeddings" in str(caught.value) and "data" in str(caught.value)


async def test_the_general_read_timeout_applies(build):
    script = Script(reply(RECORDED))
    await build(script).embed(BODY)
    assert script.requests[0].extensions["timeout"]["read"] == 60.0


async def test_a_503_is_not_replayed(build):
    script = Script(httpx2.Response(503, json={"error": {"message": "down"}}))
    with pytest.raises(PerplexityError) as caught:
        await build(script).embed(BODY)
    assert caught.value.category == "upstream_failure" and len(script.requests) == 1


async def test_a_read_timeout_is_network_timeout_after_one_request(build):
    script = Script(httpx2.ReadTimeout)
    with pytest.raises(PerplexityError) as caught:
        await build(script).embed(BODY)
    assert caught.value.category == "network_timeout" and len(script.requests) == 1


async def test_a_connect_failure_is_retried(build):
    script = Script(httpx2.ConnectError, reply(RECORDED))
    result = await build(script).embed(BODY)
    assert len(result.data) == 2 and len(script.requests) == 2


async def test_a_429_with_retry_after_is_replayed_after_the_wait(build):
    script = Script(
        httpx2.Response(429, json={"error": {"message": "slow"}}, headers={"Retry-After": "1"}),
        reply(RECORDED),
    )
    client = build(script)
    result = await client.embed(BODY)
    assert len(result.data) == 2 and len(script.requests) == 2 and max(client.sleeps) >= 1


@pytest.mark.parametrize(
    ("name", "status", "category", "text"),
    [
        ("embeddings_513_inputs_400.json", 400, "invalid_request", "maximum of 512 items"),
        ("embeddings_dim_2000_06b_400.json", 400, "invalid_request", "must not exceed 1024"),
        ("embeddings_unauthenticated_401.json", 401, "authentication", ""),
    ],
)
async def test_recorded_errors_map_and_keep_the_apis_message(
    build, make_settings, name, status, category, text
):
    with pytest.raises(PerplexityError) as caught:
        await build(Script(reply(name, status))).embed(BODY)
    assert caught.value.category == category and text in str(caught.value)
    assert make_settings().api_key.get_secret_value() not in str(caught.value)


async def test_a_400_echoing_a_key_shaped_token_is_redacted(build):
    token = "pplx-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
    script = Script(httpx2.Response(400, json={"error": {"message": f"bad {token}"}}))
    with pytest.raises(PerplexityError) as caught:
        await build(script).embed(BODY)
    assert token not in str(caught.value) and token not in (caught.value.api_message or "")


async def test_the_log_record_has_path_status_request_id_and_no_text_or_vector(build, caplog):
    meta = fixture("embeddings_two_4b_dim256.meta.json")
    request_id = meta["response_headers"]["x-request-id"]
    body = fixture(RECORDED)
    script = Script(httpx2.Response(200, json=body, headers={"x-request-id": request_id}))
    with caplog.at_level(logging.DEBUG):
        await build(script).embed({**BODY, "input": ["distinctive-input-text-zq"]})
    text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "/v1/embeddings" in text and "200" in text and request_id in text
    assert "distinctive-input-text-zq" not in text
    assert body["data"][0]["embedding"] not in text

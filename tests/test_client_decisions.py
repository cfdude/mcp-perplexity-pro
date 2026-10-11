"""Task 1.2 (py-decisions-tool): ``PerplexityClient.decide`` over a request-capturing transport."""

import json
import logging

import httpx2
import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.models import DecisionsResponse

BODY = {"model": "pplx-decider-v1.1-27b", "state": "s", "questions": {}}


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


async def test_the_recorded_three_question_response_comes_back(build):
    script = Script(reply("decisions_three_questions.json"))
    result = await build(script).decide(BODY)
    raw = fixture("decisions_three_questions.json")
    assert isinstance(result, DecisionsResponse)
    assert result.model == raw["model"] and list(result.answers) == ["urgent", "area", "severity"]
    assert result.usage == {"input_tokens": 347, "output_tokens": 3}
    (request,) = script.requests
    assert request.method == "POST" and request.url.path == "/v1/decisions"
    assert json.loads(request.content) == BODY


async def test_odd_values_are_kept_and_missing_answers_raise(build):
    odd = {"answers": {"q": "stray"}, "usage": None}
    result = await build(Script(httpx2.Response(200, json=odd))).decide(BODY)
    assert result.answers == {"q": "stray"} and result.usage is None
    for body in ({"model": "x"}, {"answers": [1]}):
        with pytest.raises(PerplexityError) as caught:
            await build(Script(httpx2.Response(200, json=body))).decide(BODY)
        assert caught.value.category == "unexpected_response"
        assert "/v1/decisions" in str(caught.value) and "answers" in str(caught.value)


async def test_the_general_read_timeout_applies(build):
    script = Script(reply("decisions_noul.json"))
    await build(script).decide(BODY)
    assert script.requests[0].extensions["timeout"]["read"] == 60.0


async def test_a_503_is_not_replayed(build):
    script = Script(httpx2.Response(503, json={"error": {"message": "down"}}))
    with pytest.raises(PerplexityError) as caught:
        await build(script).decide(BODY)
    assert caught.value.category == "upstream_failure" and len(script.requests) == 1


async def test_a_read_timeout_is_network_timeout_after_one_request(build):
    script = Script(httpx2.ReadTimeout)
    with pytest.raises(PerplexityError) as caught:
        await build(script).decide(BODY)
    assert caught.value.category == "network_timeout" and len(script.requests) == 1


async def test_a_429_with_retry_after_is_replayed_after_the_wait(build):
    script = Script(
        httpx2.Response(429, json={"error": {"message": "slow"}}, headers={"Retry-After": "1"}),
        reply("decisions_noul.json"),
    )
    client = build(script)
    result = await client.decide(BODY)
    assert result.model and len(script.requests) == 2 and max(client.sleeps) >= 1


@pytest.mark.parametrize(
    ("name", "status", "category", "text"),
    [
        ("decisions_129_questions_400.json", 400, "invalid_request", "between 1 and 128 questions"),
        ("decisions_unknown_model_400.json", 400, "invalid_request", "Invalid model"),
        ("decisions_unauthenticated_401.json", 401, "authentication", ""),
    ],
)
async def test_recorded_errors_map_and_keep_the_apis_message(
    build, make_settings, name, status, category, text
):
    with pytest.raises(PerplexityError) as caught:
        await build(Script(reply(name, status))).decide(BODY)
    assert caught.value.category == category and text in str(caught.value)
    assert make_settings().api_key.get_secret_value() not in str(caught.value)


async def test_a_400_echoing_a_key_shaped_token_is_redacted(build):
    token = "pplx-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
    script = Script(httpx2.Response(400, json={"error": {"message": f"bad {token}"}}))
    with pytest.raises(PerplexityError) as caught:
        await build(script).decide(BODY)
    assert token not in str(caught.value) and token not in (caught.value.api_message or "")


async def test_the_log_record_has_path_status_and_request_id_and_no_state(build, caplog):
    request_id = fixture("decisions_noul.meta.json")["response_headers"]["x-request-id"]
    script = Script(
        httpx2.Response(
            200, json=fixture("decisions_noul.json"), headers={"x-request-id": request_id}
        )
    )
    body = {"model": "m", "state": "distinctive-state-text-zq", "questions": {}}
    with caplog.at_level(logging.DEBUG):
        await build(script).decide(body)
    text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "/v1/decisions" in text and "200" in text and request_id in text
    assert "distinctive-state-text-zq" not in text

"""routing-v2 probe fixtures (tasks 1.1 and 1.5): the captured shapes the router and the matrix
build on, pinned so a later change cannot silently drift from what the API really answered."""

import json

from fixture_support import FIXTURE_DIR


def _load(name):
    body = json.loads((FIXTURE_DIR / f"{name}.json").read_text())
    meta = json.loads((FIXTURE_DIR / f"{name}.meta.json").read_text())
    return body, meta


def test_model_with_effort_and_web_search_shape():
    body, meta = _load("agent_model_effort_web_search")
    assert meta["http_status"] == 200
    assert meta["request"]["reasoning"] == {"effort": "low"}
    assert meta["request"]["tools"] == [{"type": "web_search"}]
    assert meta["request"]["max_steps"] == 3
    assert body["status"] == "completed"
    assert body["model"] == "openai/gpt-6-luna"
    # the response echoes the level it ran at, under reasoning
    assert body["reasoning"]["effort"] == "low"
    usage = body["usage"]
    assert usage["cost"]["total_cost"] > 0
    assert usage["tool_calls_details"]["search_web"]["invocation"] >= 1
    assert {"input_tokens", "output_tokens", "input_tokens_details"} <= set(usage)


def test_strongest_candidate_medium_figures_for_the_pilot():
    body, meta = _load("agent_opus55_medium_web_search")
    assert meta["request"]["reasoning"] == {"effort": "medium"}
    assert body["model"] == "anthropic/claude-opus-5-5"
    assert body["reasoning"]["effort"] == "medium"
    usage = body["usage"]
    details = usage["input_tokens_details"]
    # the figures the pilot of 7.1b and the evaluation caps start from
    assert usage["input_tokens"] > 0 and usage["output_tokens"] > 0
    assert "cache_creation_input_tokens" in details and "cached_tokens" in details
    assert usage["tool_calls_details"]["search_web"]["invocation"] >= 1
    assert usage["cost"]["total_cost"] > 0
    assert meta["latency_seconds"] > 0


def test_a_model_the_api_does_not_serve_is_a_400_naming_the_model():
    body, meta = _load("agent_model_not_served_400")
    assert meta["http_status"] == 400
    assert meta["request"]["model"] == "openai/gpt-99-luna"
    error = body["error"]
    assert error["type"] == "invalid_request" and error["code"] == 400
    assert error["message"] == 'validation failed: model "openai/gpt-99-luna" is not supported'
    # rejected before a run exists: no usage block, no id
    assert "usage" not in body and "id" not in body
    assert meta["latency_seconds"] < 2


def test_an_unknown_response_id_poll_is_a_404_that_names_no_model():
    body, meta = _load("agent_get_unknown_404")
    assert meta["http_status"] == 404
    assert body["error"]["message"] == "resource not found"
    assert "model" not in body["error"]["message"]


def test_an_effort_refusal_is_the_generic_invalid_request_400():
    body, meta = _load("agent_effort_refused_400")
    assert meta["http_status"] == 400
    assert meta["request"]["reasoning"] == {"effort": "xhigh"}
    error = body["error"]
    # NOT the named 'validation failed' text of an unknown model or an unknown level: nothing in
    # the body says it is the level, so is_effort_refusal can only use the fallback rule of D17
    assert error["message"] == "invalid request"
    assert error["type"] == "invalid_request"
    assert "usage" not in body and "id" not in body

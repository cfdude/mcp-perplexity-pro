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

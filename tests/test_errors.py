"""Error taxonomy: eight stable categories, status mapping, sanitized messages."""

import json

import pytest
from fastmcp.exceptions import ToolError
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.errors import CATEGORIES, PerplexityError, error_from_response


def test_category_vocabulary_is_stable():
    assert CATEGORIES == (
        "invalid_request",
        "authentication",
        "forbidden",
        "not_found",
        "rate_limited",
        "upstream_failure",
        "network_timeout",
        "unexpected_response",
    )


def test_perplexity_error_is_a_tool_error():
    assert issubclass(PerplexityError, ToolError)


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (400, "invalid_request"),
        (422, "invalid_request"),
        (401, "authentication"),
        (403, "forbidden"),
        (404, "not_found"),
        (429, "rate_limited"),
        (500, "upstream_failure"),
        (502, "upstream_failure"),
        (503, "upstream_failure"),
        (599, "upstream_failure"),
        (413, "unexpected_response"),
        (402, "unexpected_response"),
        (405, "unexpected_response"),
        (409, "unexpected_response"),
        (301, "unexpected_response"),
        (302, "unexpected_response"),
        (307, "unexpected_response"),
    ],
)
def test_status_maps_to_category(status, category):
    body = json.dumps({"error": {"message": "boom", "type": "t", "code": status}})
    err = error_from_response(status, body)
    assert isinstance(err, PerplexityError)
    assert err.category == category
    assert err.status == status
    assert "boom" in str(err)


def test_413_carries_status_and_message():
    err = error_from_response(413, '{"error": {"message": "too big", "type": "x", "code": 413}}')
    assert err.category == "unexpected_response"
    assert err.status == 413
    assert "too big" in str(err)


def test_recorded_chat_completions_not_available_403():
    body = (FIXTURE_DIR / "chat_completions_403.json").read_text()
    err = error_from_response(403, body)
    assert err.category == "forbidden"
    assert err.status == 403
    assert err.api_type == "chat_completions_not_available"
    assert err.api_code == 403
    assert "chat_completions_not_available" in str(err)
    assert "/v1/responses" in str(err)


def test_recorded_validation_400():
    body = (FIXTURE_DIR / "agent_anthropic_no_max_output_tokens_400.json").read_text()
    err = error_from_response(400, body)
    assert err.category == "invalid_request"
    assert "max_output_tokens is required" in str(err)


def test_recorded_401():
    err = error_from_response(401, (FIXTURE_DIR / "models_unauthenticated.json").read_text())
    assert err.category == "authentication"
    assert err.api_type == "invalid_api_key"


@pytest.mark.parametrize("body", ["", "not json", "[]", '{"error": "str"}', '{"error": {}}'])
def test_unparseable_or_partial_bodies_still_give_an_error(body):
    err = error_from_response(500, body)
    assert err.category == "upstream_failure"
    assert err.status == 500
    assert str(err)  # never empty
    assert err.api_type is None


def test_message_is_sanitized_of_key_shaped_tokens():
    token = "pplx-" + "Zz9_" * 10
    body = json.dumps({"error": {"message": f"bad key {token}", "type": "invalid_api_key"}})
    err = error_from_response(401, body)
    assert token not in str(err)
    assert "[redacted]" in str(err)


def test_non_status_errors_have_no_status():
    err = PerplexityError("network_timeout", "read timeout elapsed")
    assert err.status is None
    assert err.category == "network_timeout"


def test_unknown_category_is_rejected():
    with pytest.raises(ValueError):
        PerplexityError("nope", "x")

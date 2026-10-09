"""Task 3.3: ``agent_response_status`` decides what a caller records (design D7)."""

import json

import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.usage import agent_response_status


def fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("agent_background_submit.json", None),
        ("agent_background_poll_pending.json", None),
        ("agent_background_poll.json", "ok"),
        ("agent_fast.json", "ok"),
    ],
)
def test_recorded_fixtures(name, expected):
    assert agent_response_status(fixture(name)) == expected


def mutated(**changes):
    body = fixture("agent_background_poll.json")
    body.update(changes)
    return body


@pytest.mark.parametrize(
    "response",
    [
        mutated(status="failed"),
        mutated(status="incomplete"),
        mutated(status="cancelled"),
        mutated(status=5),
        mutated(error={"message": "boom"}),
        mutated(status="queued", error={"message": "boom"}),
        None,
        "completed",
        ["completed"],
    ],
    ids=[
        "failed",
        "incomplete",
        "other",
        "non-str",
        "error",
        "queued+error",
        "none",
        "str",
        "list",
    ],
)
def test_anything_else_is_unexpected_response(response):
    assert agent_response_status(response) == "unexpected_response"


def test_in_progress_is_not_recorded():
    assert agent_response_status(mutated(status="in_progress")) is None


def test_an_absent_status_with_a_null_error_is_ok():
    body = fixture("agent_fast.json")
    del body["status"]
    assert agent_response_status(body) == "ok"
    body["status"] = None
    assert agent_response_status(body) == "ok"


def test_it_never_raises_on_a_hostile_mapping():
    class Hostile(dict):
        def get(self, *args):
            raise RuntimeError("boom")

    assert agent_response_status(Hostile()) == "unexpected_response"

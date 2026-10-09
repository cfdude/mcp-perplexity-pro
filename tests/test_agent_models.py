"""Task 1.2: Agent API response models against every recorded 200 capture."""

import json

import pytest
from fixture_support import FIXTURE_DIR
from pydantic import ValidationError

from mcp_perplexity_pro.models import AgentRun, CancelResponse

NOT_RUNS = {"agent_cancel_accepted", "agent_response_headers"}


def load(name):
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


def sidecar(name):
    return json.loads((FIXTURE_DIR / f"{name}.meta.json").read_text())


def run_captures():
    names = []
    for meta in sorted(FIXTURE_DIR.glob("agent_*.meta.json")):
        name = meta.name.removesuffix(".meta.json")
        body = load(name)
        if (
            sidecar(name)["http_status"] == 200
            and isinstance(body, dict)
            and "id" in body
            and name not in NOT_RUNS
        ):
            names.append(name)
    return names


def test_the_table_covers_every_run_capture():
    names = run_captures()
    assert "agent_background_cancelled" in names
    assert "agent_fast" in names
    assert len(names) == 17  # 29 agent captures minus the 400s/404s and the two non-runs


@pytest.mark.parametrize("name", run_captures())
def test_every_recorded_run_parses_with_unknown_fields_retained(name):
    body = load(name)
    run = AgentRun.model_validate(body)
    assert (run.id, run.status) == (body["id"], body["status"])
    dumped = run.model_dump(mode="json")
    for key, value in body.items():  # unknown fields (object, created_at, ...) are kept
        assert dumped[key] == value, key


def test_cancel_accepted_is_a_cancel_response_not_a_run():
    body = load("agent_cancel_accepted")
    cancel = CancelResponse.model_validate(body)
    assert (cancel.response_id, cancel.status) == (body["response_id"], "cancelling")
    with pytest.raises(ValidationError):
        AgentRun.model_validate(body)  # no id


def test_the_headers_sample_is_neither():
    body = load("agent_response_headers")
    for model in (AgentRun, CancelResponse):
        with pytest.raises(ValidationError):
            model.model_validate(body)


def test_unknown_output_item_type_is_kept_as_received():
    item = {"type": "brand_new_tool_call", "payload": {"a": [1, 2]}}
    run = AgentRun.model_validate({"id": "resp_1", "status": "completed", "output": [item]})
    assert run.output == [item]


@pytest.mark.parametrize("output", [{"type": "message"}, "just text"])
def test_output_that_is_not_a_list_is_kept(output):
    run = AgentRun.model_validate({"id": "resp_1", "status": "completed", "output": output})
    assert run.output == output


def test_queued_run_has_no_usage_and_empty_output():
    run = AgentRun.model_validate(load("agent_background_submit_medium"))
    assert (run.status, run.usage, run.output) == ("queued", None, [])
    bare = AgentRun.model_validate({"id": "resp_1", "status": "queued"})
    assert bare.output == [] and bare.usage is None and bare.model is None and bare.error is None


@pytest.mark.parametrize(
    "body", [{"status": "completed"}, {"id": "resp_1"}, {"id": "resp_1", "status": None}]
)
def test_a_run_without_id_or_status_is_rejected(body):
    with pytest.raises(ValidationError):
        AgentRun.model_validate(body)

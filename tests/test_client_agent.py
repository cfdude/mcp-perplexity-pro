"""Task 1.3: the Agent API client operations over a request-capturing MockTransport."""

import json
import logging

import httpx2
import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.models import AgentRun, CancelResponse

COMPLETED_ID = "resp_d60f3e03-57e0-4048-994f-69b29a6d2ce7"


def fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def reply(name, status=200, headers=None):
    return httpx2.Response(status, json=fixture(name), headers=headers)


class Script:
    """Plays a list of responses/exceptions in order (the last repeats) and records requests."""

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
    async def no_sleep(_):
        return None

    def factory(script, **settings):
        return PerplexityClient(
            make_settings(**settings), transport=httpx2.MockTransport(script), sleep=no_sleep
        )

    return factory


# --- create / fetch / cancel ----------------------------------------------------------------


async def test_create_returns_the_recorded_fast_run(build):
    script = Script(reply("agent_fast.json"))
    run = await build(script).create_run({"preset": "fast", "input": "q"}, background=False)
    raw = fixture("agent_fast.json")
    assert isinstance(run, AgentRun)
    assert (run.id, run.status, run.model) == (raw["id"], "completed", raw["model"])
    assert run.output == raw["output"] and run.usage == raw["usage"]
    request = script.requests[0]
    assert (request.method, request.url.path) == ("POST", "/v1/agent")
    assert json.loads(request.content) == {"preset": "fast", "input": "q"}


async def test_fetch_returns_the_completed_snapshot(build):
    script = Script(reply("agent_background_completed.json"))
    run = await build(script).get_run(COMPLETED_ID)
    assert run.status == "completed"
    assert run.output[-1]["type"] == "message"
    assert (script.requests[0].method, script.requests[0].url.path) == (
        "GET",
        f"/v1/agent/{COMPLETED_ID}",
    )


async def test_cancel_returns_the_cancelling_response(build):
    script = Script(reply("agent_cancel_accepted.json"))
    cancelled = await build(script).cancel_run(COMPLETED_ID)
    assert isinstance(cancelled, CancelResponse)
    assert (cancelled.response_id, cancelled.status) == (
        fixture("agent_cancel_accepted.json")["response_id"],
        "cancelling",
    )
    assert script.requests[0].url.path == f"/v1/agent/{COMPLETED_ID}/cancel"
    assert script.requests[0].method == "POST"


# --- response id check ---------------------------------------------------------------------


@pytest.mark.parametrize("operation", ["get_run", "cancel_run"])
@pytest.mark.parametrize(
    "bad",
    [
        "resp_x/../../v1/models",
        "resp_",
        "x",
        "resp_a b",
        "resp_" + "a" * 101,
        "resp_é",
        "resp_a\n",
        "",
    ],
)
async def test_a_bad_response_id_is_refused_before_any_request(build, operation, bad):
    script = Script(reply("agent_fast.json"))
    with pytest.raises(PerplexityError) as info:
        await getattr(build(script), operation)(bad)
    assert info.value.category == "invalid_request"
    assert script.requests == []


async def test_edge_length_ids_are_accepted(build):
    script = Script(reply("agent_background_completed.json"))
    await build(script).get_run("resp_" + "a-_Z9" * 20)  # 100 characters after resp_
    assert len(script.requests) == 1


async def test_recorded_id_goes_into_the_path(build):
    script = Script(reply("agent_background_completed.json"))
    await build(script).get_run(COMPLETED_ID)
    assert str(script.requests[0].url).endswith(f"/v1/agent/{COMPLETED_ID}")


# --- tolerant parsing through the existing parse -------------------------------------------


async def test_unknown_output_item_is_retained_through_the_client(build):
    body = {"id": "resp_1", "status": "completed", "output": [{"type": "novel", "x": 1}]}
    run = await build(Script(httpx2.Response(200, json=body))).create_run({}, background=False)
    assert run.output == [{"type": "novel", "x": 1}]


async def test_queued_submit_has_no_usage_and_empty_output(build):
    script = Script(reply("agent_background_submit_medium.json"))
    run = await build(script).create_run({"background": True}, background=True)
    assert (run.status, run.usage, run.output) == ("queued", None, [])


async def test_a_response_without_status_is_unexpected_response_naming_path_and_field(build):
    script = Script(httpx2.Response(200, json={"id": "resp_1"}))
    with pytest.raises(PerplexityError) as info:
        await build(script).create_run({}, background=False)
    assert info.value.category == "unexpected_response"
    assert "/v1/agent" in str(info.value) and "status" in str(info.value)


# --- timeouts ------------------------------------------------------------------------------


def timeouts(request):
    return request.extensions["timeout"]


async def test_synchronous_create_carries_the_agent_read_timeout(build):
    script = Script(reply("agent_fast.json"))
    client = build(script)
    await client.create_run({}, background=False)
    sent = timeouts(script.requests[0])
    assert (sent["read"], sent["write"]) == (120, 120)
    assert (sent["connect"], sent["pool"]) == (10, 10)  # unchanged
    assert client._timeout.read == 60  # the general read timeout is untouched


async def test_a_larger_configured_agent_timeout_is_used(build):
    script = Script(reply("agent_fast.json"))
    await build(script, agent_read_timeout=240).create_run({}, background=False)
    assert timeouts(script.requests[0])["read"] == 240


async def test_background_submit_fetch_and_cancel_use_the_general_timeout(build):
    script = Script(
        reply("agent_background_submit_medium.json"),
        reply("agent_background_completed.json"),
        reply("agent_cancel_accepted.json"),
    )
    client = build(script)
    await client.create_run({"background": True}, background=True)
    await client.get_run(COMPLETED_ID)
    await client.cancel_run(COMPLETED_ID)
    for request in script.requests:
        assert (timeouts(request)["read"], timeouts(request)["write"]) == (60, 60)


async def test_synchronous_read_timeout_states_120_and_is_not_replayed(build):
    script = Script(httpx2.ReadTimeout)
    with pytest.raises(PerplexityError) as info:
        await build(script).create_run({}, background=False)
    assert info.value.category == "network_timeout"
    assert "read timeout (120s)" in str(info.value)
    assert len(script.requests) == 1


async def test_the_general_timeout_error_still_states_its_own_value(build):
    script = Script(httpx2.ReadTimeout)
    with pytest.raises(PerplexityError) as info:
        await build(script, max_attempts=1).get_run(COMPLETED_ID)
    assert "read timeout (60s)" in str(info.value)


# --- retry rules ---------------------------------------------------------------------------


def error(status):
    return httpx2.Response(status, json={"error": {"message": "down", "type": "x", "code": status}})


async def test_5xx_on_create_is_one_request(build):
    script = Script(error(503), reply("agent_fast.json"))
    with pytest.raises(PerplexityError) as info:
        await build(script).create_run({}, background=False)
    assert info.value.category == "upstream_failure"
    assert len(script.requests) == 1


async def test_5xx_on_cancel_is_one_request(build):
    script = Script(error(503), reply("agent_cancel_accepted.json"))
    with pytest.raises(PerplexityError) as info:
        await build(script).cancel_run(COMPLETED_ID)
    assert info.value.category == "upstream_failure"
    assert len(script.requests) == 1


async def test_5xx_on_fetch_is_retried(build):
    script = Script(error(503), reply("agent_background_completed.json"))
    run = await build(script).get_run(COMPLETED_ID)
    assert run.status == "completed"
    assert len(script.requests) == 2


# --- error mapping and api_message ---------------------------------------------------------


async def test_validation_message_passes_through(build):
    script = Script(reply("agent_structured_bad_root_400.json", 400))
    with pytest.raises(PerplexityError) as info:
        await build(script).create_run({}, background=False)
    assert info.value.category == "invalid_request"
    assert "json_schema.schema must have a root type of 'object'" in str(info.value)
    assert info.value.api_type == "invalid_parameter"


async def test_unknown_run_is_not_found(build):
    script = Script(reply("agent_get_unknown_404.json", 404))
    with pytest.raises(PerplexityError) as info:
        await build(script).get_run(COMPLETED_ID)
    assert info.value.category == "not_found"


async def test_unknown_and_finished_cancel_failures_are_identical(build):
    messages = []
    for name in ("agent_cancel_unknown_400.json", "agent_cancel_terminal_400.json"):
        with pytest.raises(PerplexityError) as info:
            await build(Script(reply(name, 400))).cancel_run(COMPLETED_ID)
        assert info.value.category == "invalid_request"
        messages.append(str(info.value))
    assert messages[0] == messages[1]


async def test_generic_400_keeps_the_exact_api_message_and_type(build):
    script = Script(reply("agent_chat_bad_previous_response_400.json", 400))
    with pytest.raises(PerplexityError) as info:
        await build(script).create_run({}, background=False)
    err = info.value
    assert err.api_message == "invalid request"
    assert err.api_type == "invalid_request"
    assert err.status == 400
    assert "invalid_request" in str(err) and str(err) != err.api_message  # readable names type


async def test_api_message_is_redacted(build):
    token = "pplx-" + "Zz9_" * 10
    body = {"error": {"message": f"bad {token} and test-dummy-api-key", "type": "t", "code": 400}}
    with pytest.raises(PerplexityError) as info:
        await build(Script(httpx2.Response(400, json=body))).create_run({}, background=False)
    assert token not in info.value.api_message
    assert "test-dummy-api-key" not in info.value.api_message
    assert info.value.api_message.startswith("bad ")


async def test_api_message_is_absent_when_the_body_has_none(build):
    with pytest.raises(PerplexityError) as info:
        await build(Script(httpx2.Response(502, text="<html>"))).create_run({}, background=False)
    assert info.value.api_message is None


# --- diagnostics ---------------------------------------------------------------------------


async def test_one_log_record_with_the_request_id_and_no_query_text(build, caplog):
    caplog.set_level(logging.DEBUG, logger="mcp_perplexity_pro")
    headers = fixture("agent_response_headers.json")["headers"]
    request_id = headers["x-request-id"]
    script = Script(reply("agent_fast.json", headers={"x-request-id": request_id}))
    await build(script).create_run(
        {"preset": "fast", "input": "SECRET-QUERY-TEXT"}, background=False
    )
    records = [r for r in caplog.records if r.name == "mcp_perplexity_pro.client"]
    assert len(records) == 1
    record = records[0]
    assert (record.http_path, record.http_status, record.request_id) == (
        "/v1/agent",
        200,
        request_id,
    )
    rendered = "\n".join(str(v) for v in record.__dict__.values()) + record.getMessage()
    assert "SECRET-QUERY-TEXT" not in rendered

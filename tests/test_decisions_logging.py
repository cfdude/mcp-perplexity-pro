"""Task 5.3 (py-decisions-tool): the logging rule for the decisions tool
(``docs/lessons/framework-logs-carry-bound-parameters.md``).

A decision stores no content, so only its usage event is written, and the state, the questions
and the answers never reach a log: the client logs method, path, status and request id; a failing
event insert logs the failure, not the request.

Mutation check: adding a log call that interpolates the request body to
``PerplexityClient.decide`` turns every test here red.
"""

import logging

import httpx2
from agent_support import fixture, make_world, respond_body, respond_with
from sqlalchemy import text

TOOL = "perplexity_decide"
STATE = "zq-distinctive-state-text-5521"
QUESTION = "zq-distinctive-question-name-9983"
ASKS = {QUESTION: {"type": "noul", "instructions": "zq-distinctive-instructions-3302"}}


def own_log(caplog) -> str:
    fmt = logging.Formatter()
    return "\n".join(
        fmt.format(r) for r in caplog.records if r.name.startswith("mcp_perplexity_pro")
    )


async def test_a_forced_event_insert_failure_logs_without_state_questions_or_answers(
    make_settings, caplog
):
    body = fixture("decisions_noul.json")
    body["answers"] = {QUESTION: {"type": "choice", "choice": "zq-distinctive-answer-7714"}}
    w = await make_world(make_settings, respond_body(body))
    try:
        async with w.engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TRIGGER veto_usage BEFORE INSERT ON usage_events "
                    "BEGIN SELECT RAISE(ABORT, 'vetoed'); END"
                )
            )
        with caplog.at_level(logging.DEBUG):
            result = await w.call(TOOL, state=STATE, questions=ASKS)
        assert not result.is_error and "zq-distinctive-answer-7714" in result.content[0].text
        assert await w.count("usage_events") == 0
        logged = own_log(caplog)
        assert "usage event not recorded" in logged
        for secret in (
            STATE,
            QUESTION,
            "zq-distinctive-answer-7714",
            "zq-distinctive-instructions",
        ):
            assert secret not in logged
        assert "[parameters" not in logged
    finally:
        await w.aclose()


async def test_a_failed_decision_log_holds_method_path_and_status_only(make_settings, caplog):
    w = await make_world(make_settings, respond_with("decisions_129_questions_400.json", 400))
    try:
        with caplog.at_level(logging.DEBUG):
            result = await w.call(TOOL, state=STATE, questions=ASKS)
        assert result.is_error
        logged = own_log(caplog)
        assert "/v1/decisions" in logged and "400" in logged
        assert STATE not in logged and QUESTION not in logged and "instructions" not in logged
        calls = [r for r in caplog.records if r.name == "mcp_perplexity_pro.client"]
        assert calls and all(
            getattr(r, "http_method", None) == "POST"
            and getattr(r, "http_path", None) == "/v1/decisions"
            for r in calls
        )
    finally:
        await w.aclose()


async def test_a_503_log_never_carries_the_request_body(make_settings, caplog):
    w = await make_world(
        make_settings, lambda request, n: httpx2.Response(503, json={"error": {"message": "down"}})
    )
    try:
        with caplog.at_level(logging.DEBUG):
            await w.call(TOOL, state=STATE, questions=ASKS)
        logged = own_log(caplog)
        assert STATE not in logged and QUESTION not in logged
    finally:
        await w.aclose()

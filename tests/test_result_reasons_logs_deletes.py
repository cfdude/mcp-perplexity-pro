"""Gate 2 fix-ups (group C): stored failure reasons reach the user, stored content stays out of
the logs, and a project delete says how many runs are still going."""

import logging

import pytest
from chat_support import FIRST, TURN_A, category, sequence
from research_support import COMPLETED, IN_PROGRESS, routes, seed_job
from sqlalchemy import text

JOBS = "perplexity_jobs"
PROJECTS = "perplexity_projects"


def log_text(caplog) -> str:
    """What THIS server's own loggers wrote (a library's own records are not under test here;
    the redacting handler's treatment of them is in test_log_setup)."""
    fmt = logging.Formatter()
    return "\n".join(
        fmt.format(r) for r in caplog.records if r.name.startswith("mcp_perplexity_pro")
    )


async def veto(w, table, event="UPDATE"):
    async with w.engine.begin() as conn:
        await conn.execute(
            text(
                f"CREATE TRIGGER veto_{table} BEFORE {event} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'vetoed'); END"
            )
        )


# --- 13. the stored reasons are returned ------------------------------------------------------


async def test_result_of_a_failed_run_carries_its_stored_error_text(research_world):
    w = await research_world()
    jid = await seed_job(w, status="failed", usage_recorded=1, error_text="the tool crashed")
    result = await w.call(JOBS, action="result", job_id=jid)
    out = result.structured_content
    assert "the run failed" in out["message"].lower() and "the tool crashed" in out["message"]
    assert "the tool crashed" in result.content[0].text


async def test_result_of_an_incomplete_run_carries_its_stored_reason(research_world):
    w = await research_world()
    jid = await seed_job(
        w, status="incomplete", usage_recorded=1, incomplete_reason="max_output_tokens"
    )
    result = await w.call(JOBS, action="result", job_id=jid)
    assert "max_output_tokens" in result.structured_content["message"]
    assert "max_output_tokens" in result.content[0].text


async def test_a_cancelled_run_whose_reason_equals_its_error_says_it_once(research_world):
    w = await research_world()
    jid = await seed_job(
        w,
        status="cancelled",
        usage_recorded=1,
        incomplete_reason="cancelled",
        error_text="cancelled",
    )
    out = (await w.call(JOBS, action="result", job_id=jid)).structured_content
    assert out["message"].lower().count("cancelled") == 2  # "was cancelled" + "Reason: cancelled"
    assert "Error:" not in out["message"]


# --- 14. stored content stays out of the logs -------------------------------------------------


async def test_a_failed_chat_write_logs_no_stored_content(chat_world, caplog):
    w = await chat_world(sequence(TURN_A))
    async with w.engine.begin() as conn:  # a failure that is not an integrity error
        await conn.execute(text("DROP TABLE chat_messages"))
    caplog.set_level(logging.DEBUG)
    secret_text = "UNIQUE-CHAT-TEXT-98765"
    result = await w.call("perplexity_chat", action="send", title="t", message=secret_text)
    assert [x for x in result.structured_content["warnings"] if x.startswith("not_saved")]
    logged = log_text(caplog)
    assert "chat write failed" in logged and "no such table" in logged
    assert secret_text not in logged and "[parameters" not in logged and FIRST not in logged


async def test_a_failed_job_row_update_logs_no_stored_content(research_world, caplog):
    w = await research_world(routes(get=[COMPLETED]))
    await seed_job(w)
    await veto(w, "research_jobs")
    caplog.set_level(logging.DEBUG)
    await w.call(JOBS, action="list", refresh=True)  # the refresh path
    result = await w.call(JOBS, action="status", job_id=1)  # the unexpected-error path
    assert category(result) == "internal_error"
    logged = log_text(caplog)
    assert "vetoed" in logged and "[parameters" not in logged
    assert "PELICAN" not in logged and "UPDATE research_jobs" not in logged


async def test_a_failed_cancel_record_logs_no_bound_values(research_world, caplog):
    from research_support import CANCEL_ACCEPTED

    w = await research_world(routes(get=[IN_PROGRESS], cancel=[CANCEL_ACCEPTED]))
    await seed_job(w)
    async with w.engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TRIGGER veto_cancel BEFORE UPDATE ON research_jobs "
                "WHEN NEW.cancel_requested_at IS NOT NULL "
                "BEGIN SELECT RAISE(ABORT, 'vetoed'); END"
            )
        )
    caplog.set_level(logging.DEBUG)
    await w.call(JOBS, action="cancel", job_id=1)
    logged = log_text(caplog)
    assert "cancel_requested_at not saved" in logged and "vetoed" in logged
    assert "[parameters" not in logged and "[SQL" not in logged


# --- 15. delete names the running jobs --------------------------------------------------------


async def test_delete_without_confirm_names_the_running_jobs_and_deletes_nothing(research_world):
    w = await research_world(routes(get=[IN_PROGRESS]))
    await seed_job(w, project="alpha", response_id="resp_a-1")
    await seed_job(w, project="alpha", response_id="resp_b-1")
    await seed_job(w, project="alpha", status="completed", usage_recorded=1, response_id="resp_c-1")
    await seed_job(w, project="other", response_id="resp_d-1")
    result = await w.call(PROJECTS, action="delete", project="alpha")
    assert category(result) == "confirmation_required"
    message = result.structured_content["message"]
    assert "2 research job(s)" in message and "billing" in message and "confirm=true" in message
    assert await w.count("research_jobs") == 4


async def test_a_confirmed_delete_reports_the_running_jobs_it_dropped(research_world):
    w = await research_world()
    await seed_job(w, project="alpha", response_id="resp_a-1")
    await seed_job(w, project="alpha", status="lost", response_id="resp_b-1")
    result = await w.call(PROJECTS, action="delete", project="alpha", confirm=True)
    assert not result.is_error and result.structured_content["running_jobs"] == 1
    assert (
        "1 research job(s)" in result.content[0].text
        and "never be recorded" in result.content[0].text
    )
    assert await w.count("research_jobs") == 0


@pytest.mark.parametrize("confirm", [False, True])
async def test_no_running_jobs_adds_no_warning(research_world, confirm):
    w = await research_world()
    await seed_job(w, project="alpha", status="completed", usage_recorded=1)
    result = await w.call(PROJECTS, action="delete", project="alpha", confirm=confirm)
    text_out = result.structured_content.get("message") or result.content[0].text
    assert "research job(s)" not in text_out
    if confirm:
        assert result.structured_content["running_jobs"] == 0

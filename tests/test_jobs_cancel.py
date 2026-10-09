"""Task 4.5: ``perplexity_jobs`` cancel (agent-research "Cancel", "A cancel that was accepted is
not lost to a local failure", "Jobs result vocabulary" scenario "Cancelling is not stored").
Every test reads the request log: what was NOT sent matters as much as what was."""

import pytest
from chat_support import category
from research_support import (
    CANCEL_ACCEPTED,
    CANCEL_TERMINAL_400,
    CANCELLED,
    CANCELLED_ID,
    COMPLETED,
    GET_404,
    IN_PROGRESS,
    Clock,
    job,
    request_log,
    routes,
    seed_job,
)
from sqlalchemy import text

TOOL = "perplexity_jobs"
GET = f"GET /v1/agent/{CANCELLED_ID}"
POST = f"POST /v1/agent/{CANCELLED_ID}/cancel"


async def cancel(w, job_id=1, **kw):
    return await w.call(TOOL, action="cancel", job_id=job_id, **kw)


async def test_a_running_job_is_cancelled_with_one_request_and_reported_cancelling(research_world):
    clock = Clock()
    w = await research_world(routes(get=[IN_PROGRESS], cancel=[CANCEL_ACCEPTED]), clock=clock)
    jid = await seed_job(w, response_id=CANCELLED_ID)
    clock.advance(minutes=2)
    out = (await cancel(w, jid)).structured_content
    assert request_log(w) == [GET, POST]  # read first, then exactly one cancel
    assert out["job_id"] == jid and out["status"] == "cancelling"
    assert out["job"]["job_id"] == jid and out["job"]["status"] == "in_progress"  # not stored
    assert out["job"]["cancel_requested_at"].startswith("2026-10-09T12:02:00")
    row = await job(w, jid)
    assert row["status"] == "in_progress" and row["cancel_requested_at"] is not None
    assert await w.count("usage_events") == 0


async def test_a_later_fetch_shows_cancelled_and_records_one_event(research_world):
    w = await research_world(routes(get=[IN_PROGRESS, CANCELLED], cancel=[CANCEL_ACCEPTED]))
    jid = await seed_job(w, response_id=CANCELLED_ID)
    await cancel(w, jid)
    out = (await w.call(TOOL, action="status", job_id=jid)).structured_content
    assert out["status"] == "cancelled" and out["job"]["status"] == "cancelled"
    assert [e[2] for e in await w.events()] == ["unexpected_response"]


async def test_a_cancel_rejected_as_terminal_refetches_once_and_reports_the_real_state(
    research_world,
):
    w = await research_world(
        routes(get=[IN_PROGRESS, COMPLETED], cancel=[(CANCEL_TERMINAL_400, 400)])
    )
    jid = await seed_job(w, response_id=CANCELLED_ID)
    result = await cancel(w, jid)
    out = result.structured_content
    assert not result.is_error and out["status"] == "completed"
    assert request_log(w) == [GET, POST, GET]  # one more fetch, not an error
    assert await w.count("usage_events") == 1  # the finished run recorded once
    assert (await job(w, jid))["status"] == "completed"


async def test_a_terminal_rejection_with_the_run_still_running_says_so(research_world):
    w = await research_world(
        routes(get=[IN_PROGRESS, IN_PROGRESS], cancel=[(CANCEL_TERMINAL_400, 400)])
    )
    jid = await seed_job(w, response_id=CANCELLED_ID)
    out = (await cancel(w, jid)).structured_content
    assert out["status"] == "in_progress" and any("already terminal" in x for x in out["warnings"])
    assert request_log(w) == [GET, POST, GET]


async def test_a_finished_job_is_reported_with_no_request_at_all(research_world):
    w = await research_world()
    jid = await seed_job(w, status="completed", usage_recorded=1)
    out = (await cancel(w, jid)).structured_content
    assert out["status"] == "completed" and out["message"] is None
    assert w.requests == []


async def test_a_second_cancel_on_a_pending_one_fetches_again_and_sends_no_second_post(
    research_world,
):
    w = await research_world(routes(get=[IN_PROGRESS], cancel=[CANCEL_ACCEPTED]))
    jid = await seed_job(w, response_id=CANCELLED_ID)
    await cancel(w, jid)
    out = (await cancel(w, jid)).structured_content
    assert out["status"] == "cancelling"
    assert request_log(w) == [GET, POST, GET]  # the second cancel: one GET, no POST
    assert await w.count("usage_events") == 0


async def test_a_second_cancel_whose_fetch_shows_cancelled_records_it_and_sends_no_post(
    research_world,
):
    w = await research_world(routes(get=[CANCELLED], cancel=[CANCEL_ACCEPTED]))
    jid = await seed_job(
        w,
        response_id=CANCELLED_ID,
        cancel_requested_at=Clock().value,  # a cancel is pending
    )
    out = (await cancel(w, jid)).structured_content
    assert out["status"] == "cancelled" and out["job"]["status"] == "cancelled"
    assert request_log(w) == [GET]  # no cancel request
    assert [e[2] for e in await w.events()] == ["unexpected_response"]


async def test_an_unknown_run_is_not_cancelled_and_stays_running_with_a_warning(research_world):
    w = await research_world(routes(get=[(GET_404, 404)], cancel=[(CANCEL_TERMINAL_400, 400)]))
    jid = await seed_job(w, response_id=CANCELLED_ID)
    result = await cancel(w, jid)
    out = result.structured_content
    assert not result.is_error and out["status"] == "in_progress" and out["warnings"]
    assert request_log(w) == [GET]  # a bare cancel would have been misread as "already terminal"
    assert (await job(w, jid))["missing_since"] is not None
    assert await w.count("usage_events") == 0


async def test_two_concurrent_cancels_of_one_job_send_exactly_one_request(research_world):
    import asyncio

    from research_support import serve

    async def responder(request, n):
        if request.method == "GET":
            return serve(IN_PROGRESS)
        await asyncio.sleep(0.2)  # the window in which a second cancel would also pass the check
        return serve(CANCEL_ACCEPTED)

    w = await research_world(responder)
    jid = await seed_job(w, response_id=CANCELLED_ID)
    first, second = await asyncio.gather(cancel(w, jid), cancel(w, jid))
    assert [r for r in request_log(w) if r.startswith("POST")] == [POST]
    assert {first.structured_content["status"], second.structured_content["status"]} == {
        "cancelling"
    }
    assert (await job(w, jid))["cancel_requested_at"] is not None


async def test_a_local_failure_after_an_accepted_cancel_still_returns_cancelling(research_world):
    w = await research_world(routes(get=[IN_PROGRESS], cancel=[CANCEL_ACCEPTED]))
    jid = await seed_job(w, response_id=CANCELLED_ID)
    async with w.engine.begin() as conn:  # veto only the write that records the cancel
        await conn.execute(
            text(
                "CREATE TRIGGER veto_cancel BEFORE UPDATE ON research_jobs "
                "WHEN NEW.cancel_requested_at IS NOT NULL "
                "BEGIN SELECT RAISE(ABORT, 'vetoed'); END"
            )
        )
    result = await cancel(w, jid)
    out = result.structured_content
    assert not result.is_error and out["status"] == "cancelling"
    assert [x for x in out["warnings"] if x.startswith("not_saved")]
    assert request_log(w) == [GET, POST]
    assert (await job(w, jid))["cancel_requested_at"] is None  # the write did not happen


async def test_a_failed_fetch_stops_the_cancel_before_any_request_to_cancel(research_world):
    import httpx2

    boom = httpx2.Response(503, json={"error": {"message": "down", "type": "x"}})
    w = await research_world(routes(get=[boom], cancel=[CANCEL_ACCEPTED]))
    jid = await seed_job(w, response_id=CANCELLED_ID)
    assert category(await cancel(w, jid)) == "upstream_failure"
    assert request_log(w) == [GET]


async def test_a_cancel_rejected_for_another_reason_is_an_error(research_world):
    import httpx2

    other = httpx2.Response(400, json={"error": {"message": "bad id", "type": "invalid_request"}})
    w = await research_world(routes(get=[IN_PROGRESS], cancel=[other]))
    jid = await seed_job(w, response_id=CANCELLED_ID)
    assert category(await cancel(w, jid)) == "invalid_request"
    assert request_log(w) == [GET, POST]  # no refetch for a rejection that is not "terminal"


@pytest.mark.parametrize("project", ["ghost", None])
async def test_cancel_of_an_unknown_job_or_in_an_absent_project_is_not_found(
    research_world, project
):
    w = await research_world()
    kwargs = {"project": project} if project else {}
    assert category(await cancel(w, 999, **kwargs)) == "not_found"
    assert w.requests == []
    assert await w.count("projects") == 0

"""Task 4.3: the job observation core (agent-research "Terminal states are observed once",
"Overlapping observations record once", "Unsuccessful terminal runs are recorded",
"Observations commit per job", "Recording follows the recorder contract", "The model is known
only from a finished run"). Driven through ``agent.observe_job`` on a server built by
``build_server``; the tools that call it are 4.4 and 4.5."""

import asyncio
import json

import pytest
from agent_support import fixture, inline
from research_support import (
    CANCELLED,
    CANCELLED_ID,
    COMPLETED,
    IN_PROGRESS,
    RUN_ID,
    SUBMIT,
    T0,
    Clock,
    job,
    routes,
    seed_job,
    serve,
)
from sqlalchemy import text

from mcp_perplexity_pro.agent import (
    observe_job,
    search_progress,
    snapshot_model,
    terminal_status,
)

TOOL = "perplexity_research"
ANSWER = [i for i in fixture(COMPLETED)["output"] if i["type"] == "message"][-1]["content"][-1][
    "text"
]
URLS = []
for _item in fixture(COMPLETED)["output"]:
    for _row in _item.get("results", []) + _item.get("contents", []):
        if _row["url"] not in URLS:
            URLS.append(_row["url"])


async def observe(w, job_id=1, project="default"):
    (pid,) = (await w.rows("SELECT id FROM projects WHERE name = :n", n=project))[0]
    return await observe_job(w.server.app, project_id=pid, project=project, job_id=job_id)


async def veto_updates(w):
    async with w.engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TRIGGER veto_update BEFORE UPDATE ON research_jobs "
                "BEGIN SELECT RAISE(ABORT, 'vetoed'); END"
            )
        )


async def allow_updates(w):
    async with w.engine.begin() as conn:
        await conn.execute(text("DROP TRIGGER veto_update"))


def gets(w):
    return [r for r in w.requests if r.method == "GET"]


# --- terminal snapshots ----------------------------------------------------------------------


async def test_a_completed_run_stores_its_result_and_records_exactly_one_event(research_world):
    # a short busy timeout: a recorder wrongly run inside the row's write unit would lose its
    # event to the lock (the recorder-order mutation check)
    clock = Clock()
    w = await research_world(routes(get=[COMPLETED]), clock=clock, db_busy_timeout=0.3)
    await seed_job(w, project="alpha", started_at=T0)
    clock.advance(minutes=5)
    seen = await observe(w, project="alpha")
    assert seen.state == "completed" and seen.fetched
    row = await job(w)
    assert row["status"] == "completed" and row["result_text"] == ANSWER
    assert [s["url"] for s in json.loads(row["sources_json"])] == URLS
    assert row["model"] == "openai/gpt-6-luna" and row["usage_recorded"] == 1
    assert (row["input_tokens"], row["output_tokens"], row["total_tokens"]) == (24463, 1085, 25548)
    assert (row["cost_nano_usd"], row["cost_source"]) == (15990000, "reported")
    assert row["finished_at"] == "2026-10-09 12:05:00.000000"  # OUR clock
    assert await w.events() == [
        (
            TOOL,
            "agent",
            "ok",
            "medium",
            "openai/gpt-6-luna",
            RUN_ID,
            "alpha",
            15990000,
            "reported",
        )
    ]
    (latency,) = (await w.rows("SELECT latency_ms FROM usage_events"))[0]
    assert latency == 5 * 60 * 1000  # from the job's start to the observation


async def test_a_cancelled_run_records_one_failure_with_no_model_cost_zero_and_no_answer(
    research_world,
):
    w = await research_world(routes(get=[CANCELLED]))
    await seed_job(w, response_id=CANCELLED_ID)
    await observe(w)
    row = await job(w)
    assert (row["status"], row["result_text"], row["model"]) == ("cancelled", None, None)
    assert row["usage_recorded"] == 1 and row["incomplete_reason"] == "cancelled"
    assert row["cost_source"] == "none" and row["error_text"] == "cancelled"
    assert await w.events() == [
        (TOOL, "agent", "unexpected_response", "medium", None, CANCELLED_ID, "default", 0, "none")
    ]


@pytest.mark.parametrize("snapshot", [IN_PROGRESS, SUBMIT])
async def test_a_pending_snapshot_records_nothing_and_leaves_the_model_empty(
    research_world, snapshot
):
    clock = Clock()
    w = await research_world(routes(get=[snapshot]), clock=clock)
    await seed_job(w, status="queued")
    clock.advance(minutes=1)
    seen = await observe(w)
    row = await job(w)
    assert seen.state == fixture(snapshot)["status"] == row["status"]
    assert row["model"] is None and row["usage_recorded"] == 0 and row["finished_at"] is None
    assert row["last_checked_at"] == "2026-10-09 12:01:00.000000"
    assert await w.count("usage_events") == 0
    if snapshot == IN_PROGRESS:
        assert search_progress(seen.run) == (3, 3)


async def test_an_unknown_status_is_stored_verbatim_and_nothing_is_recorded(research_world):
    w = await research_world(routes(get=[inline("paused", id=RUN_ID)]))
    await seed_job(w)
    seen = await observe(w)
    assert seen.state == "paused" and (await job(w))["status"] == "paused"
    assert (await job(w))["usage_recorded"] == 0
    assert await w.count("usage_events") == 0


async def test_an_error_on_an_odd_status_is_stored_failed_with_one_event(research_world):
    body = inline("paused", id=RUN_ID, error={"message": "it broke"})
    w = await research_world(routes(get=[body]))
    await seed_job(w)
    await observe(w)
    row = await job(w)
    assert (row["status"], row["error_text"], row["usage_recorded"]) == ("failed", "it broke", 1)
    assert [e[2] for e in await w.events()] == ["unexpected_response"]
    await observe(w)  # terminal: no later fetch
    assert len(gets(w)) == 1


async def test_a_failed_run_with_reported_usage_is_recorded_with_that_cost(research_world):
    usage = {
        "input_tokens": 10,
        "output_tokens": 2,
        "cost": {"total_cost": 0.002, "currency": "USD"},
    }
    body = inline("failed", id=RUN_ID, usage=usage, error={"message": "late failure"})
    w = await research_world(routes(get=[body]))
    await seed_job(w)
    await observe(w)
    (event,) = await w.events()
    assert event[2] == "unexpected_response" and event[7:] == (2000000, "reported")
    assert (await job(w))["cost_nano_usd"] == 2000000


async def test_the_same_terminal_snapshot_observed_twice_leaves_one_event_and_one_fetch(
    research_world,
):
    w = await research_world(routes(get=[COMPLETED]))
    await seed_job(w)
    first, second = await observe(w), await observe(w)
    assert first.fetched and not second.fetched and second.state == "completed"
    assert len(gets(w)) == 1 and await w.count("usage_events") == 1


async def test_the_stored_start_time_survives_snapshots_with_different_created_at(research_world):
    assert fixture(IN_PROGRESS)["created_at"] != fixture(COMPLETED)["created_at"]
    w = await research_world(routes(get=[IN_PROGRESS, COMPLETED]))
    await seed_job(w)
    await observe(w)
    assert (await job(w))["started_at"] == "2026-10-09 12:00:00.000000"
    await observe(w)
    row = await job(w)
    assert row["started_at"] == "2026-10-09 12:00:00.000000"
    assert not any("created_at" in str(v) for v in row.values())  # the API's times are not stored


# --- the recorder contract and the dedupe index ----------------------------------------------


async def test_a_row_update_that_fails_after_the_event_does_not_record_a_second_one(
    research_world,
):
    w = await research_world(routes(get=[COMPLETED]))
    await seed_job(w)
    await veto_updates(w)
    with pytest.raises(Exception, match="vetoed"):
        await observe(w)
    assert await w.count("usage_events") == 1  # the event outlives the failed row update
    assert (await job(w))["status"] == "in_progress"  # and the row update rolled back
    await allow_updates(w)
    await observe(w)  # observed again: the event-exists check finds it, only the row is written
    assert await w.count("usage_events") == 1
    assert (await job(w))["status"] == "completed"


async def test_two_overlapping_observations_of_a_cancelled_run_record_one_event(research_world):
    gate = asyncio.Event()

    async def responder(request, n):
        if n == 1:
            await gate.wait()  # hold the first fetch until the second observation has started
        return serve(CANCELLED)

    w = await research_world(responder)
    await seed_job(w, response_id=CANCELLED_ID)
    first = asyncio.create_task(observe(w))
    await asyncio.sleep(0.05)
    second = asyncio.create_task(observe(w))
    await asyncio.sleep(0.05)
    gate.set()
    a, b = await asyncio.gather(first, second)
    assert (a.fetched, b.fetched) == (True, False)  # the second returns the stored result
    assert b.state == "cancelled"
    assert len(gets(w)) == 1 and await w.count("usage_events") == 1


async def test_a_non_terminal_row_whose_usage_is_already_recorded_is_not_fetched_again(
    research_world,
):
    # a state only a crash or a hand edit can leave: the guard is the ONLY thing that reads it
    w = await research_world(routes(get=[COMPLETED]))
    await seed_job(w, status="in_progress", usage_recorded=1)
    seen = await observe(w)
    assert not seen.fetched and seen.state == "in_progress"
    assert w.requests == [] and await w.count("usage_events") == 0


async def test_a_cancelled_run_whose_row_update_failed_is_not_recorded_again(research_world):
    # cancelled/failed/incomplete events are ``unexpected_response``, which the partial unique
    # index (status = 'ok') does not cover: only the observation's own check stops a duplicate
    w = await research_world(routes(get=[CANCELLED]))
    await seed_job(w, response_id=CANCELLED_ID)
    await veto_updates(w)
    with pytest.raises(Exception, match="vetoed"):
        await observe(w)
    assert await w.count("usage_events") == 1
    await allow_updates(w)
    await observe(w)
    assert await w.count("usage_events") == 1  # not a second one
    row = await job(w)
    assert row["status"] == "cancelled" and row["usage_recorded"] == 1


async def test_a_client_cancel_between_the_event_and_the_row_update_still_writes_the_row(
    research_world, monkeypatch
):
    from mcp_perplexity_pro.storage import jobs as job_store

    w = await research_world(routes(get=[CANCELLED]))
    await seed_job(w, response_id=CANCELLED_ID)
    in_update = asyncio.Event()
    real = job_store.update_job

    async def slow_update(session, project_id, job_id, values):
        in_update.set()
        await asyncio.sleep(0.2)  # the client cancels the call while the row is being written
        return await real(session, project_id, job_id, values)

    monkeypatch.setattr(job_store, "update_job", slow_update)
    task = asyncio.create_task(observe(w))
    await asyncio.wait_for(in_update.wait(), 5)
    assert await w.count("usage_events") == 1  # the event exists already
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    row = await job(w)  # the cancel was re-raised only after the row was written
    assert row["status"] == "cancelled" and row["usage_recorded"] == 1
    assert await w.count("usage_events") == 1


# --- the pure rules --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "model", "depth", "expected"),
    [
        ("completed", "openai/gpt-6-luna", "medium", "openai/gpt-6-luna"),
        ("queued", "medium", "medium", None),
        ("in_progress", "medium", "medium", None),
        ("cancelled", "medium", "medium", None),
        ("in_progress", "openai/gpt-6-luna", "medium", "openai/gpt-6-luna"),
        ("failed", "medium", "high", None),
        ("in_progress", "a/b", "a/b", None),  # contains "/" but equals the depth
        ("in_progress", None, "medium", None),
    ],
)
def test_the_model_is_known_only_from_a_finished_run(status, model, depth, expected):
    assert snapshot_model({"status": status, "model": model}, depth) == expected


@pytest.mark.parametrize(
    ("status", "error", "stored"),
    [
        ("completed", None, "completed"),
        ("failed", None, "failed"),
        ("incomplete", None, "incomplete"),
        ("cancelled", {"code": "cancelled"}, "cancelled"),
        ("completed", {"message": "x"}, "failed"),
        ("paused", {"message": "x"}, "failed"),
        ("failed", {"message": "x"}, "failed"),
    ],
)
def test_a_terminal_status_is_stored_in_the_vocabulary_the_terminal_test_knows(
    status, error, stored
):
    assert terminal_status(status, error) == stored

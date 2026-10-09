"""Task 4.4: ``perplexity_jobs`` list, status and result through ``build_server`` with an
injectable clock (agent-research "Jobs tool", "Jobs result vocabulary", "Jobs actions never
create a project", "Status polls once", "Result action", "Runs the provider no longer knows",
"Listing jobs", "Observations commit per job"; local-storage "Several observations, one
fails")."""

import json

import httpx2
import jsonschema
import pytest
from agent_support import fixture, inline
from chat_support import category, message
from research_support import (
    COMPLETED,
    GET_404,
    IN_PROGRESS,
    RUN_ID,
    Clock,
    job,
    job_rows,
    request_log,
    routes,
    seed_job,
)
from sqlalchemy import text

TOOL = "perplexity_jobs"
ANSWER = [i for i in fixture(COMPLETED)["output"] if i["type"] == "message"][-1]["content"][-1][
    "text"
]
URLS = []
for _item in fixture(COMPLETED)["output"]:
    for _row in _item.get("results", []) + _item.get("contents", []):
        if _row["url"] not in URLS:
            URLS.append(_row["url"])


def gets(w):
    return [r for r in w.requests if r.method == "GET"]


async def no_upstream(w):
    assert w.requests == []


def err(status, body_message="boom"):
    return httpx2.Response(status, json={"error": {"message": body_message, "type": "x"}})


# --- listing and validation ------------------------------------------------------------------


async def test_listing_has_schema_annotations_and_honest_wording(research_world):
    from fastmcp import Client

    w = await research_world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    assert {"job_id", "status", "job", "jobs", "progress"} <= set(tool.output_schema["properties"])
    ann = tool.annotations
    assert (ann.read_only_hint, ann.destructive_hint, ann.open_world_hint) == (False, True, True)
    props = tool.input_schema["properties"]
    assert {"action", "job_id", "project", "refresh", "limit"} <= set(props)
    assert tool.input_schema["required"] == ["action"]
    desc = " ".join(tool.description.split())
    for word in ("list", "status", "result", "cancel", "refresh"):
        assert word in desc
    assert "never create a project" in desc


async def test_an_unknown_action_is_refused(research_world):
    w = await research_world()
    result = await w.call(TOOL, action="delete")
    assert category(result) == "invalid_request" and "action" in message(result)


@pytest.mark.parametrize("action", ["status", "result"])
async def test_a_by_id_action_without_job_id_is_invalid_request_naming_it(research_world, action):
    w = await research_world()
    await seed_job(w)
    result = await w.call(TOOL, action=action)
    assert category(result) == "invalid_request" and "job_id" in message(result)
    await no_upstream(w)


@pytest.mark.parametrize("action", ["status", "result"])
async def test_an_unknown_job_and_another_projects_job_are_not_found_with_no_request(
    research_world, action
):
    w = await research_world()
    mine = await seed_job(w, project="alpha")
    assert category(await w.call(TOOL, action=action, job_id=999, project="alpha")) == "not_found"
    other = await w.call(TOOL, action=action, job_id=mine, project="beta")  # beta: no such project
    assert category(other) == "not_found"
    await seed_job(w, project="beta", response_id="resp_beta-1")
    cross = await w.call(TOOL, action=action, job_id=mine, project="beta")
    assert category(cross) == "not_found" and "Job" in message(cross)
    await no_upstream(w)


@pytest.mark.parametrize("action", ["status", "result"])
async def test_a_by_id_action_in_an_absent_project_is_not_found_and_creates_nothing(
    research_world, action
):
    w = await research_world()
    result = await w.call(TOOL, action=action, job_id=1, project="ghost")
    assert category(result) == "not_found"
    await no_upstream(w)
    assert await w.count("projects") == 0 and await w.count("usage_events") == 0


async def test_list_in_an_absent_project_is_empty_and_creates_nothing(research_world):
    w = await research_world()
    for refresh in (False, True):
        out = (
            await w.call(TOOL, action="list", project="ghost", refresh=refresh)
        ).structured_content
        assert out["jobs"] == [] and out["jobs_total"] == 0 and out["truncated"] is False
    await no_upstream(w)
    assert await w.count("projects") == 0


@pytest.mark.parametrize("limit", [0, 101, -1])
async def test_a_bad_limit_is_invalid_request(research_world, limit):
    w = await research_world()
    assert category(await w.call(TOOL, action="list", limit=limit)) == "invalid_request"


# --- status ----------------------------------------------------------------------------------


async def test_a_running_job_shows_its_progress_and_records_nothing(research_world):
    w = await research_world(routes(get=[IN_PROGRESS]))
    jid = await seed_job(w, status="queued")
    out = (await w.call(TOOL, action="status", job_id=jid)).structured_content
    assert out["status"] == "in_progress" and out["job"]["status"] == "in_progress"
    assert out["progress"] == {"searches": 3, "fetches": 3}
    assert out["answer"] is None and out["usage"] is None
    assert await w.count("usage_events") == 0 and len(gets(w)) == 1


async def test_a_finished_job_is_served_locally_with_no_request(research_world):
    w = await research_world(routes(get=[COMPLETED]))
    jid = await seed_job(w, status="completed", usage_recorded=1)
    out = (await w.call(TOOL, action="status", job_id=jid)).structured_content
    assert out["status"] == "completed" and out["progress"] is None
    await no_upstream(w)


async def test_status_after_a_submit_that_came_back_completed_makes_no_request(research_world):
    w = await research_world(routes(post=[COMPLETED]))
    submitted = (await w.call("perplexity_research", query="q")).structured_content
    assert submitted["status"] == "completed"
    out = (await w.call(TOOL, action="status", job_id=submitted["job_id"])).structured_content
    assert out["status"] == "completed"
    assert request_log(w) == ["POST /v1/agent"]  # the submit only: no GET
    assert await w.count("usage_events") == 1  # recorded once, by the submit


async def test_an_unknown_status_is_stored_returned_verbatim_and_not_recorded(research_world):
    w = await research_world(routes(get=[inline("paused", id=RUN_ID)]))
    jid = await seed_job(w)
    result = await w.call(TOOL, action="status", job_id=jid)
    assert not result.is_error and result.structured_content["status"] == "paused"
    assert (await job(w, jid))["status"] == "paused"
    assert await w.count("usage_events") == 0
    again = (await w.call(TOOL, action="status", job_id=jid)).structured_content
    assert again["status"] == "paused" and len(gets(w)) == 2  # still running: fetched again


async def test_a_job_finished_by_a_status_call_is_recorded_once_across_status_and_result(
    research_world,
):
    w = await research_world(routes(get=[COMPLETED]))
    jid = await seed_job(w)
    await w.call(TOOL, action="status", job_id=jid)
    await w.call(TOOL, action="result", job_id=jid)
    await w.call(TOOL, action="status", job_id=jid)
    assert len(gets(w)) == 1 and await w.count("usage_events") == 1


# --- result ----------------------------------------------------------------------------------


async def test_result_returns_the_answer_sources_cost_and_the_stored_token_columns(research_world):
    w = await research_world(routes(get=[COMPLETED]))
    jid = await seed_job(w)
    await w.call(TOOL, action="status", job_id=jid)
    async with w.engine.begin() as conn:  # the figures must come from the columns, not a re-parse
        await conn.execute(text("UPDATE research_jobs SET input_tokens = 111"))
    result = await w.call(TOOL, action="result", job_id=jid)
    out = result.structured_content
    assert out["answer"] == ANSWER and out["message"] is None and out["status"] == "completed"
    assert [s["url"] for s in out["sources"]] == URLS
    assert out["usage"] == {
        "input_tokens": 111,
        "output_tokens": 1085,
        "total_tokens": 25548,
        "cost_usd": "0.01599",
        "cost_source": "reported",
    }
    assert ANSWER in result.content[0].text and "0.01599" in result.content[0].text
    assert len(gets(w)) == 1


async def test_result_of_a_running_job_has_no_answer_and_says_to_try_again(research_world):
    w = await research_world(routes(get=[IN_PROGRESS]))
    jid = await seed_job(w)
    out = (await w.call(TOOL, action="result", job_id=jid)).structured_content
    assert out["status"] == "in_progress" and out["answer"] is None and out["usage"] is None
    assert "try again later" in out["message"] and "not finished" in out["message"]


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("cancelled", "cancelled"),
        ("failed", "failed"),
        ("incomplete", "stopped before it finished"),
        ("lost", "no longer knows"),
    ],
)
async def test_result_of_a_job_with_no_answer_says_why(research_world, status, reason):
    w = await research_world()
    jid = await seed_job(w, status=status, usage_recorded=0 if status == "lost" else 1)
    out = (await w.call(TOOL, action="result", job_id=jid)).structured_content
    assert out["status"] == status and out["answer"] is None and reason in out["message"]
    await no_upstream(w)


# --- runs the provider no longer knows -------------------------------------------------------


async def test_the_first_404_keeps_the_job_running_with_a_warning_and_no_event(research_world):
    clock = Clock()
    w = await research_world(routes(get=[(GET_404, 404)]), clock=clock)
    jid = await seed_job(w)
    clock.advance(minutes=1)
    result = await w.call(TOOL, action="status", job_id=jid)
    out = result.structured_content
    assert not result.is_error and out["status"] == "in_progress" and out["warnings"]
    row = await job(w, jid)
    assert row["missing_since"] == "2026-10-09 12:01:00.000000" and row["status"] == "in_progress"
    assert await w.count("usage_events") == 0
    assert [r.method for r in w.requests] == ["GET"]  # no cancel request, ever


async def test_a_second_404_after_ten_minutes_marks_the_job_lost_for_good(research_world):
    clock = Clock()
    w = await research_world(routes(get=[(GET_404, 404)]), clock=clock)
    jid = await seed_job(w)
    clock.advance(minutes=1)
    await w.call(TOOL, action="status", job_id=jid)  # the first 404
    clock.advance(minutes=10)  # 11 minutes after submit
    out = (await w.call(TOOL, action="status", job_id=jid)).structured_content
    assert out["status"] == "lost" and out["job"]["status"] == "lost"
    assert any("not recorded" in x for x in out["warnings"])
    assert (await job(w, jid))["status"] == "lost" and await w.count("usage_events") == 0
    before = len(gets(w))
    later = (await w.call(TOOL, action="status", job_id=jid)).structured_content
    assert later["status"] == "lost" and len(gets(w)) == before  # no later fetch


async def test_a_second_404_too_early_leaves_the_job_running(research_world):
    clock = Clock()
    w = await research_world(routes(get=[(GET_404, 404)]), clock=clock)
    jid = await seed_job(w)
    clock.advance(minutes=1)
    await w.call(TOOL, action="status", job_id=jid)
    clock.advance(minutes=1)  # 2 minutes after submit
    out = (await w.call(TOOL, action="status", job_id=jid)).structured_content
    assert out["status"] == "in_progress" and out["warnings"]
    assert (await job(w, jid))["status"] == "in_progress"


async def test_a_first_404_on_an_old_job_never_marks_it_lost(research_world):
    # the lost rule needs a SECOND not_found: age alone must not decide it
    clock = Clock()
    w = await research_world(routes(get=[(GET_404, 404)]), clock=clock)
    jid = await seed_job(w)
    clock.advance(minutes=11)
    out = (await w.call(TOOL, action="status", job_id=jid)).structured_content
    assert out["status"] == "in_progress" and out["warnings"]
    row = await job(w, jid)
    assert row["status"] == "in_progress" and row["missing_since"] is not None
    assert await w.count("usage_events") == 0


async def test_every_404_records_when_the_job_was_last_checked(research_world):
    clock = Clock()
    w = await research_world(routes(get=[(GET_404, 404)]), clock=clock)
    jid = await seed_job(w)
    clock.advance(minutes=1)
    await w.call(TOOL, action="status", job_id=jid)
    assert (await job(w, jid))["last_checked_at"] == "2026-10-09 12:01:00.000000"
    clock.advance(minutes=1)  # a second 404, too early to be lost
    await w.call(TOOL, action="status", job_id=jid)
    assert (await job(w, jid))["last_checked_at"] == "2026-10-09 12:02:00.000000"


async def test_a_successful_fetch_clears_the_missing_record(research_world):
    clock = Clock()
    w = await research_world(routes(get=[(GET_404, 404), IN_PROGRESS]), clock=clock)
    jid = await seed_job(w)
    await w.call(TOOL, action="status", job_id=jid)
    assert (await job(w, jid))["missing_since"] is not None
    await w.call(TOOL, action="status", job_id=jid)
    assert (await job(w, jid))["missing_since"] is None


# --- list ------------------------------------------------------------------------------------


async def test_a_plain_list_is_newest_first_honors_limit_and_makes_no_request(research_world):
    w = await research_world()
    done = await seed_job(w, status="completed", usage_recorded=1, response_id="resp_a-1")
    running = await seed_job(w, query="q" * 300, response_id="resp_b-1")
    third = await seed_job(w, response_id="resp_c-1")
    out = (await w.call(TOOL, action="list")).structured_content
    assert [j["job_id"] for j in out["jobs"]] == [third, running, done]
    assert out["jobs_total"] == 3 and out["truncated"] is False and out["not_refreshed"] is None
    by_id = {j["job_id"]: j for j in out["jobs"]}
    assert len(by_id[running]["query_excerpt"]) == 120
    assert by_id[done]["usage_recorded"] is True and by_id[running]["usage_recorded"] is False
    cut = (await w.call(TOOL, action="list", limit=2)).structured_content
    assert [j["job_id"] for j in cut["jobs"]] == [third, running]
    assert cut["jobs_total"] == 3 and cut["truncated"] is True
    await no_upstream(w)


async def test_the_list_says_a_usage_event_was_attempted_and_n_a_for_a_lost_job(research_world):
    from mcp_perplexity_pro.tools.jobs import JobInfo

    w = await research_world()
    await seed_job(w, status="completed", usage_recorded=1, response_id="resp_a-1")
    await seed_job(w, response_id="resp_b-1")
    await seed_job(w, status="lost", response_id="resp_c-1")
    text_out = (await w.call(TOOL, action="list")).content[0].text
    lines = {line.split(".")[0]: line for line in text_out.splitlines()[1:]}
    assert "usage event attempted" in lines["1"] and "usage recorded" not in text_out
    assert "usage not yet attempted" in lines["2"]
    assert "usage n/a" in lines["3"] and "lost" in lines["3"]
    field = JobInfo.model_json_schema()["properties"]["usage_recorded"]["description"]
    assert "attempted" in field and "usage report" not in field


async def test_refresh_settles_a_finished_run_into_one_event(research_world):
    w = await research_world(routes(get=[COMPLETED]))
    jid = await seed_job(w)
    out = (await w.call(TOOL, action="list", refresh=True)).structured_content
    assert out["jobs"][0]["status"] == "completed" and out["jobs"][0]["usage_recorded"] is True
    assert out["not_refreshed"] == 0 and await w.count("usage_events") == 1
    await w.call(TOOL, action="list", refresh=True)  # nothing left to observe
    assert len(gets(w)) == 1 and (await job(w, jid))["status"] == "completed"


async def test_refresh_is_bounded_and_starts_with_the_jobs_never_checked(research_world):
    w = await research_world(routes(get=[IN_PROGRESS]))
    ids = []
    for n in range(12):  # jobs 1..10 were checked (job n at minute n), jobs 11 and 12 never
        checked = None if n >= 10 else f"2026-10-09 11:{n:02d}:00.000000"
        row = await seed_job(w, response_id=f"resp_bulk-{n}")
        ids.append(row)
        if checked:
            async with w.engine.begin() as conn:
                await conn.execute(
                    text("UPDATE research_jobs SET last_checked_at = :t WHERE id = :i"),
                    {"t": checked, "i": row},
                )
    out = (await w.call(TOOL, action="list", refresh=True)).structured_content
    fetched = [r.url.path.rsplit("/", 1)[1] for r in gets(w)]
    assert len(fetched) == 10 and out["not_refreshed"] == 2
    # the two never checked first (ties by id), then the least recently checked: jobs 1..8
    assert fetched == [f"resp_bulk-{n}" for n in (10, 11, 0, 1, 2, 3, 4, 5, 6, 7)]
    # the next refresh rotates to the ones left out (job 9 and 10 were never refreshed)
    await w.call(TOOL, action="list", refresh=True)
    second = [r.url.path.rsplit("/", 1)[1] for r in gets(w)][10:]
    assert second[:2] == ["resp_bulk-8", "resp_bulk-9"]


async def test_one_observation_whose_row_update_fails_does_not_undo_the_others(research_world):
    w = await research_world(routes(get=[COMPLETED]))
    ids = [await seed_job(w, response_id=f"resp_three-{n}") for n in range(3)]
    async with w.engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TRIGGER veto_second BEFORE UPDATE ON research_jobs WHEN OLD.id = :i "
                "BEGIN SELECT RAISE(ABORT, 'vetoed'); END".replace(":i", str(ids[1]))
            )
        )
    result = await w.call(TOOL, action="list", refresh=True)
    out = result.structured_content
    rows = {r["id"]: r for r in await job_rows(w)}
    assert [rows[i]["status"] for i in ids] == ["completed", "in_progress", "completed"]
    assert [rows[i]["usage_recorded"] for i in ids] == [1, 0, 1]
    assert await w.count("usage_events") == 3  # the second's event outlives its failed update
    assert any(f"Job {ids[1]}" in x and "internal_error" in x for x in out["warnings"])
    assert out["not_refreshed"] == 1 and len(out["jobs"]) == 3


async def test_a_failing_fetch_in_refresh_is_a_warning_and_the_list_is_still_returned(
    research_world,
):
    w = await research_world(routes(get=[COMPLETED, err(503), COMPLETED]))
    ids = [await seed_job(w, response_id=f"resp_flaky-{n}") for n in range(3)]
    result = await w.call(TOOL, action="list", refresh=True)
    out = result.structured_content
    assert not result.is_error and out["not_refreshed"] == 1 and len(out["jobs"]) == 3
    assert [x for x in out["warnings"] if f"Job {ids[1]}" in x and "upstream_failure" in x]
    rows = {r["id"]: r for r in await job_rows(w)}
    assert [rows[i]["status"] for i in ids] == ["completed", "in_progress", "completed"]
    assert await w.count("usage_events") == 2


# --- vocabulary and schema -------------------------------------------------------------------


async def test_every_action_carries_the_pinned_ids_and_states_and_validates(research_world):
    from fastmcp import Client

    w = await research_world(routes(get=[COMPLETED]))
    jid = await seed_job(w)
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
        results = {
            "status": await client.call_tool(TOOL, {"action": "status", "job_id": jid}),
            "result": await client.call_tool(TOOL, {"action": "result", "job_id": jid}),
            "list": await client.call_tool(TOOL, {"action": "list"}),
        }
    for action, result in results.items():
        out = result.structured_content
        jsonschema.validate(out, tool.output_schema)
        assert out["action"] == action and out["project"] == "default"
        if action == "list":
            assert out["job_id"] is None and out["status"] is None and out["job"] is None
            assert [j["job_id"] for j in out["jobs"]] == [jid]
            assert out["jobs"][0]["status"] == "completed"
        else:
            assert out["job_id"] == jid and out["status"] == "completed"
            assert out["job"]["job_id"] == jid and out["job"]["status"] == "completed"
            assert out["jobs"] is None
    json.dumps(results["result"].structured_content)  # plain JSON: money is a string, no floats

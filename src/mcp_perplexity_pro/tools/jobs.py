"""``perplexity_jobs``: manage research runs started by ``perplexity_research`` (agent-research).

No action waits for a run to progress. Every action looks the project up and never creates it
(design D15). Observing a run (fetch, record its usage once, store the result) is
``agent.observe_job``, each observation its own unit of work (design D8); this module decides
which jobs to observe and how to report what was found.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_perplexity_pro.agent import (
    DEFAULT_PROJECT,
    REFRESH_LIMIT,
    Observation,
    Source,
    UsageSummary,
    error_category,
    observe_job,
    search_progress,
    stored_usage,
)
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage import jobs as job_store
from mcp_perplexity_pro.storage.models import ResearchJob
from mcp_perplexity_pro.storage.projects import find_project, validate_project_name
from mcp_perplexity_pro.storage.session import unit_of_work

logger = logging.getLogger(__name__)

TOOL = "perplexity_jobs"
ACTIONS = ("list", "status", "result", "cancel")
DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT = 20, 100
EXCERPT_CHARS = 120
WHY_NO_ANSWER = {
    "cancelled": "The run was cancelled, so it has no answer.",
    "failed": "The run failed, so it has no answer.",
    "incomplete": "The run stopped before it finished, so it has no answer.",
    "lost": "The provider no longer knows this run, so its answer cannot be retrieved.",
}


class JobInfo(BaseModel):
    job_id: Annotated[int, Field(description="The local job id")]
    response_id: Annotated[str, Field(description="The provider's response id")]
    depth: Annotated[str, Field(description="The preset: medium, high or xhigh")]
    status: Annotated[
        str, Field(description="The STORED status (a pending cancel is not shown here)")
    ]
    query_excerpt: Annotated[str, Field(description="The first 120 characters of the query")]
    model: Annotated[str | None, Field(description="The model, known once the run finished")] = None
    started_at: Annotated[datetime, Field(description="When it was submitted (UTC, our clock)")]
    finished_at: Annotated[
        datetime | None, Field(description="When a call saw it finish (UTC)")
    ] = None
    cancel_requested_at: Annotated[
        datetime | None, Field(description="When a cancel was accepted (UTC)")
    ] = None
    usage_recorded: Annotated[
        bool, Field(description="Whether its spend is in the usage report yet")
    ]


class Progress(BaseModel):
    searches: Annotated[int, Field(description="Search steps the run has shown so far")]
    fetches: Annotated[int, Field(description="Page-fetch steps the run has shown so far")]


class JobsResult(BaseModel):
    """The result of every action; the fields an action does not use are null (design D10)."""

    action: Annotated[str, Field(description="The action that ran")]
    project: Annotated[str, Field(description="The project the action ran in")]
    job_id: Annotated[
        int | None, Field(description="The job the action concerns; null for list")
    ] = None
    status: Annotated[
        str | None,
        Field(
            description="The state the action reports (null for list): queued, in_progress, "
            "completed, failed, incomplete, cancelled, lost, cancelling (cancel only, never "
            "stored) or an unknown API status verbatim"
        ),
    ] = None
    job: Annotated[JobInfo | None, Field(description="The job's stored record")] = None
    jobs: Annotated[list[JobInfo] | None, Field(description="Jobs found (list only)")] = None
    jobs_total: Annotated[int | None, Field(description="All jobs in the project (list)")] = None
    truncated: Annotated[bool | None, Field(description="Whether limit cut the list")] = None
    answer: Annotated[str | None, Field(description="result: the stored answer text")] = None
    sources: Annotated[list[Source], Field(description="result: pages the run touched")] = []
    usage: Annotated[
        UsageSummary | None, Field(description="result: tokens and cost of a finished run")
    ] = None
    progress: Annotated[
        Progress | None, Field(description="Steps shown by the snapshot this call fetched")
    ] = None
    warnings: Annotated[list[str], Field(description="Things worth knowing about this result")] = []
    message: Annotated[str | None, Field(description="What the result means or to do next")] = None
    not_refreshed: Annotated[
        int | None,
        Field(description="list with refresh: running jobs not refreshed (beyond 10, or failed)"),
    ] = None


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def job_info(job: ResearchJob) -> JobInfo:
    return JobInfo(
        job_id=job.id,
        response_id=job.response_id,
        depth=job.depth,
        status=job.status,
        query_excerpt=job.query[:EXCERPT_CHARS],
        model=job.model,
        started_at=_utc(job.started_at),  # type: ignore[arg-type]
        finished_at=_utc(job.finished_at),
        cancel_requested_at=_utc(job.cancel_requested_at),
        usage_recorded=bool(job.usage_recorded),
    )


def _sources(job: ResearchJob) -> list[Source]:
    if not job.sources_json:
        return []
    try:
        return [Source(**item) for item in json.loads(job.sources_json)]
    except (ValueError, TypeError):
        return []  # a hand-edited row must not break reading the job


def _bad(option: str, message: str) -> PerplexityError:
    return PerplexityError("invalid_request", f"{option}: {message}")


def _not_found_project(name: str) -> PerplexityError:
    return PerplexityError("not_found", f"No project named {name!r}.")


def _need_job_id(job_id: int | None, action: str) -> int:
    if job_id is None:
        raise _bad("job_id", f"{action} needs a job_id.")
    return job_id


async def _find(app: Any, name: str, job_id: int) -> tuple[int, ResearchJob]:
    """The project and the job inside it, looked up and never created, before any upstream
    call: another project's job, or an absent one, is ``not_found``."""
    async with unit_of_work(app.engine, write=False) as session:
        found = await find_project(session, name)
        if found is None:
            raise _not_found_project(name)
        return found.id, await job_store.load_job(session, found.id, job_id)


def _progress(obs: Observation) -> Progress | None:
    if obs.run is None:
        return None
    searches, fetches = search_progress(obs.run)
    return Progress(searches=searches, fetches=fetches)


def _line(job: JobInfo) -> str:
    return (
        f"{job.job_id}. [{job.status}] {job.depth} {job.query_excerpt!r} "
        f"(started {job.started_at:%Y-%m-%d %H:%M} UTC"
        + (f", finished {job.finished_at:%H:%M}" if job.finished_at else "")
        + (", usage recorded" if job.usage_recorded else ", usage not yet recorded")
        + ")"
    )


def _state_text(job_id: int, state: str, obs: Observation, progress: Progress | None) -> str:
    lines = [f"Job {job_id}: {state}."]
    if progress is not None:
        lines.append(f"Progress so far: {progress.searches} searches, {progress.fetches} fetches.")
    lines.extend(f"Warning: {w}" for w in obs.warnings)
    return "\n".join(lines)


async def _status(app: Any, *, project: str | None, job_id: int | None) -> tuple[JobsResult, str]:
    job_id = _need_job_id(job_id, "status")
    name = validate_project_name(project or DEFAULT_PROJECT)
    pid, _ = await _find(app, name, job_id)
    obs = await observe_job(app, project_id=pid, project=name, job_id=job_id)
    progress = _progress(obs)
    result = JobsResult(
        action="status",
        project=name,
        job_id=job_id,
        status=obs.state,
        job=job_info(obs.job),
        progress=progress,
        warnings=obs.warnings,
    )
    return result, _state_text(job_id, obs.state, obs, progress)


async def _result(app: Any, *, project: str | None, job_id: int | None) -> tuple[JobsResult, str]:
    job_id = _need_job_id(job_id, "result")
    name = validate_project_name(project or DEFAULT_PROJECT)
    pid, _ = await _find(app, name, job_id)
    obs = await observe_job(app, project_id=pid, project=name, job_id=job_id)
    job, state = obs.job, obs.state
    final = job_store.is_final(job)
    answer = job.result_text if final else None
    if answer:
        message = None if state == "completed" else WHY_NO_ANSWER.get(state)
    elif final:
        message = WHY_NO_ANSWER.get(state, f"The run ended as {state} with no answer.")
    else:
        message = f"The run is not finished (status {state}); try again later."
    sources = _sources(job) if final else []
    usage = stored_usage(job) if final else None
    progress = _progress(obs)
    result = JobsResult(
        action="result",
        project=name,
        job_id=job_id,
        status=state,
        job=job_info(job),
        answer=answer or None,
        sources=sources,
        usage=usage,
        progress=progress,
        warnings=obs.warnings,
        message=message,
    )
    lines = [answer] if answer else [f"Job {job_id}: {state}."]
    if message:
        lines.append(message)
    lines.extend(f"Warning: {w}" for w in obs.warnings)
    if sources:
        lines.extend(["", "Sources:"])
        lines.extend(
            f"{i}. {s.title + ' - ' if s.title else ''}{s.url}" for i, s in enumerate(sources, 1)
        )
    if usage is not None:
        cost = (
            f"cost {usage.cost_usd} USD ({usage.cost_source})" if usage.cost_usd else "cost unknown"
        )
        tokens = f", {usage.total_tokens} tokens" if usage.total_tokens is not None else ""
        model = f"{job.model}, " if job.model else ""
        lines.extend(["", f"Usage: {model}{cost}{tokens}, project {name}."])
    return result, "\n".join(lines)


async def _refresh(app: Any, pid: int, name: str) -> tuple[list[str], int]:
    """Observe the project's non-final jobs, oldest-checked first, at most ``REFRESH_LIMIT``,
    each its own observation. A failed one is a warning naming the job and the category; it
    does not stop the others. Returns the warnings and how many jobs were not refreshed."""
    async with unit_of_work(app.engine, write=False) as session:
        ids, running = await job_store.refresh_candidates(session, pid, REFRESH_LIMIT)
    warnings: list[str] = []
    failed = 0
    for job_id in ids:
        try:
            obs = await observe_job(app, project_id=pid, project=name, job_id=job_id)
        except Exception as exc:
            category = error_category(exc)
            if category == "internal_error":
                logger.exception("refresh: observing job %s failed", job_id)
            warnings.append(f"Job {job_id} was not refreshed ({category}).")
            failed += 1
            continue
        warnings.extend(f"Job {job_id}: {w}" for w in obs.warnings)
    return warnings, failed + max(running - len(ids), 0)


async def _list(
    app: Any, *, project: str | None, limit: int | None, refresh: bool
) -> tuple[JobsResult, str]:
    cap = DEFAULT_LIST_LIMIT if limit is None else limit
    if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= MAX_LIST_LIMIT:
        raise _bad("limit", f"must be a whole number from 1 to {MAX_LIST_LIMIT}.")
    name = validate_project_name(project or DEFAULT_PROJECT)
    async with unit_of_work(app.engine, write=False) as session:
        found = await find_project(session, name)
    warnings: list[str] = []
    not_refreshed = None
    jobs: list[ResearchJob] = []
    total = 0
    if found is not None:
        if refresh:
            warnings, not_refreshed = await _refresh(app, found.id, name)
        async with unit_of_work(app.engine, write=False) as session:
            jobs, total = await job_store.list_jobs(session, found.id, cap)
    elif refresh:
        not_refreshed = 0
    infos = [job_info(j) for j in jobs]
    result = JobsResult(
        action="list",
        project=name,
        jobs=infos,
        jobs_total=total,
        truncated=total > len(infos),
        warnings=warnings,
        not_refreshed=not_refreshed,
    )
    lines = [f"{len(infos)} of {total} job(s) in project {name!r}, newest first:"]
    lines.extend(_line(i) for i in infos)
    if total > len(infos):
        lines.append(f"(cut by limit {cap}; {total - len(infos)} more)")
    if not_refreshed:
        lines.append(f"{not_refreshed} running job(s) were not refreshed.")
    lines.extend(f"Warning: {w}" for w in warnings)
    return result, "\n".join(lines)


def register(server: FastMCP) -> None:
    @server.tool(
        name=TOOL,
        output_schema=JobsResult.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
    )
    async def perplexity_jobs(
        ctx: Context,
        action: Annotated[str, Field(description="list, status, result or cancel")],
        job_id: Annotated[
            int | None,
            Field(description="status, result, cancel: the job from perplexity_research"),
        ] = None,
        project: Annotated[
            str | None, Field(description="Project the job belongs to (default: default)")
        ] = None,
        refresh: Annotated[
            bool,
            Field(
                description="list: first observe the project's running jobs (up to 10, the "
                "least recently checked first) so finished runs are recorded as spend"
            ),
        ] = False,
        limit: Annotated[
            int | None, Field(description="list: jobs to return, 1 to 100 (default 20)")
        ] = None,
    ) -> ToolResult:
        """Manage research runs started by perplexity_research. Actions: list (newest first),
        status (one fetch of a running job, with progress), result (the stored answer, sources
        and cost of a finished job) and cancel (stops a running job for good). Nothing here
        waits for a run to progress: call again later.

        status, result and cancel fetch a job that is not finished at most once and then store
        what it shows; a finished job is served from the local database with no request. The
        first call that sees a run finished records its cost as spend, once: list with refresh
        true settles up to 10 running jobs, and a run nobody observes is never recorded. A run
        the provider no longer knows becomes lost after a second not-found at least 10 minutes
        after submit, and its spend cannot be recorded. Actions never create a project: list in
        an absent project is empty, the others fail with not_found."""
        if action not in ACTIONS:
            raise _bad("action", f"must be one of {', '.join(ACTIONS)}.")
        app = ctx.lifespan_context
        if action == "list":
            result, text = await _list(app, project=project, limit=limit, refresh=refresh)
        elif action == "status":
            result, text = await _status(app, project=project, job_id=job_id)
        elif action == "result":
            result, text = await _result(app, project=project, job_id=job_id)
        else:
            raise _bad("action", "cancel is not available yet.")
        return ToolResult(content=text, structured_content=result.model_dump(mode="json"))

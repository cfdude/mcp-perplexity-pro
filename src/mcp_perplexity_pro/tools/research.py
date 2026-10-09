"""``perplexity_research``: start a long run in the background (agent-research spec).

The submit goes through ``agent.run_costed`` (project committed first, no write unit open across
the call, a terminal or failed submit recorded). The job row is written afterwards, with its own
retry, because the provider has already accepted the run (design D8). Results are read, and the
run's cost recorded, by ``perplexity_jobs``.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from mcp_perplexity_pro.agent import (
    DEFAULT_RESEARCH_DEPTH,
    RESEARCH_TOOL,
    build_research_request,
    clean_text,
    error_category,
    job_columns,
    run_costed,
    shielded_write,
)
from mcp_perplexity_pro.client import is_response_id
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.redaction import scrub_secrets
from mcp_perplexity_pro.storage.jobs import insert_job
from mcp_perplexity_pro.storage.models import ResearchJob
from mcp_perplexity_pro.storage.projects import find_project
from mcp_perplexity_pro.storage.session import unit_of_work

logger = logging.getLogger(__name__)

TOOL = RESEARCH_TOOL
INSERT_ATTEMPTS = 2  # one retry (design D8)


class ResearchResult(BaseModel):
    job_id: Annotated[int, Field(description="Local job id: pass it to perplexity_jobs")]
    response_id: Annotated[str, Field(description="The provider's response id for the run")]
    status: Annotated[
        str, Field(description="The status the provider reported: usually queued or in_progress")
    ]
    depth: Annotated[str, Field(description="The preset the run uses: medium, high or xhigh")]
    project: Annotated[str, Field(description="The project the job belongs to")]
    started_at: Annotated[datetime, Field(description="When this server submitted the run (UTC)")]
    message: Annotated[str, Field(description="What to do next")]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _storage_category(exc: BaseException) -> str:
    """The category a failed insert maps to: a deleted project is ``not_found`` (retrying cannot
    help), a busy database is ``storage_busy``, anything else is ``internal_error``."""
    if isinstance(exc, IntegrityError) and "foreign key" in str(exc).lower():
        return "not_found"
    return error_category(exc)


async def _store_job(
    app: Any, project: str, response_id: str, values: dict[str, Any]
) -> ResearchJob:
    """Insert the job row, shielded from cancellation of the calling task: the provider has
    already accepted the run, so a client cancel must not leave a billed run with no handle
    (the cancel is re-raised once the write finished)."""
    return await shielded_write(_store_job_unit(app, project, response_id, values))


async def _store_job_unit(
    app: Any, project: str, response_id: str, values: dict[str, Any]
) -> ResearchJob:
    """Insert the job row, retried once. The provider has already accepted the run, so a second
    failure raises an error that carries the response id, and logs it at ERROR, so the run can be
    cancelled by hand (design D8)."""
    failure: Exception | None = None
    for _attempt in range(INSERT_ATTEMPTS):
        try:
            async with unit_of_work(app.engine) as session:
                found = await find_project(session, project)
                if found is None:
                    raise PerplexityError("not_found", f"No project named {project!r}.")
                return await insert_job(session, found.id, values)
        except Exception as exc:
            failure = exc
    assert failure is not None
    category = _storage_category(failure)
    logger.error(
        "research run %s was accepted by the provider but its job row could not be stored "
        "(%s, %s); the run keeps running and billing until cancelled by hand",
        response_id,
        category,
        type(failure).__name__,
    )
    raise PerplexityError(
        category,
        f"The research run was started at the provider (response id {response_id}) but its job "
        f"record could not be stored locally ({category}). The run keeps going and billing: "
        f"cancel it by hand through the provider (POST /v1/agent/{response_id}/cancel).",
    ) from None


def register(server: FastMCP) -> None:
    @server.tool(
        name=TOOL,
        output_schema=ResearchResult.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
    )
    async def perplexity_research(
        ctx: Context,
        query: Annotated[
            str, Field(description="The research question (at most 20000 characters)")
        ],
        depth: Annotated[
            str,
            Field(
                description="medium (default), high or xhigh; deeper runs take longer and cost "
                "more. fast and low answers belong to perplexity_ask"
            ),
        ] = DEFAULT_RESEARCH_DEPTH,
        instructions: Annotated[
            str | None, Field(description="System-style instructions, at most 10000 characters")
        ] = None,
        project: Annotated[
            str | None, Field(description="Project the job belongs to (default: default)")
        ] = None,
    ) -> ToolResult:
        """Start a deep research run in the background and return at once with a job id. The
        call never waits for the run: read progress and the result with perplexity_jobs
        (status, result, list, cancel).

        Approximate cost per run by depth (estimates from one probe and the provider's
        positioning, not measured by this server): medium about $0.016 to $0.05 and about 35
        seconds; high can cost up to about $0.4 to $0.9 and take minutes; xhigh more. There is
        no spending cap. A run is recorded as spend only once a perplexity_jobs call observes it
        finished, so call status or list with refresh true; a run nobody checks is never
        recorded.

        Research runs are stored by the provider (store is true, because a background run that
        is not stored cannot be retrieved), so the query and result stay retrievable there. The
        query and the result are also kept in this server's local database."""
        request = build_research_request(depth, query, instructions)  # everything local first
        app = ctx.lifespan_context
        started = app.now()
        costed = await run_costed(
            app,
            tool=TOOL,
            project=project,
            body=request,
            preset=depth,
            background=True,
        )
        secrets = (app.settings.api_key.get_secret_value(),)
        raw = costed.run.model_dump(mode="json")
        response_id = raw.get("id")
        if not is_response_id(response_id):
            logger.error(
                "research submit returned an unusable response id %r; no job row was stored",
                clean_text(response_id, 64, secrets),
            )
            raise PerplexityError(
                "unexpected_response",
                "The API accepted the run but returned a response id of an unexpected shape, so "
                "no job was stored.",
            )
        logger.info(  # the trail if the call is cancelled or dies before the row is stored
            "research run %s accepted by the provider (status %s); storing its job row",
            response_id,
            clean_text(raw.get("status"), 64, secrets),
        )
        # A terminal submit is stored terminal and already recorded by run_costed (usage_recorded
        # is set by job_columns); any other status is stored verbatim as a running job.
        values = {
            "query": scrub_secrets(query, secrets),  # the stored copy never holds the key
            "depth": depth,
            "response_id": response_id,
            "started_at": started,
            **job_columns(raw, depth, app.now(), secrets),
        }
        values["last_checked_at"] = None  # nothing has been fetched yet
        job = await _store_job(app, costed.project, response_id, values)
        finished = job.status in ("completed", "failed", "incomplete", "cancelled")
        message = (
            f"The run had already finished when it was submitted (status {job.status}); read it "
            "with perplexity_jobs result."
            if finished
            else "The run is going in the background. Check it with perplexity_jobs status, or "
            "list with refresh true; it is recorded as spend when a call sees it finished."
        )
        result = ResearchResult(
            job_id=job.id,
            response_id=job.response_id,
            status=job.status,
            depth=job.depth,
            project=costed.project,
            started_at=_utc(job.started_at),
            message=message,
        )
        return ToolResult(
            content=f"Research job {job.id} ({job.depth}, {job.status}) in project "
            f"{costed.project!r}. {message}",
            structured_content=result.model_dump(mode="json"),
        )

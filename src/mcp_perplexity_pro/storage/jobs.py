"""Research job storage operations (agent-research spec; design D7).

Every function runs inside the caller's unit of work and never opens one, so the caller decides
what is one write: a submit's insert is one unit, and each observation's row update is its own
(design D8). A write whose job or project is gone raises ``PerplexityError`` ``not_found``:
retrying cannot help.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.models import ResearchJob

# A stored status in this set is final: nothing is fetched or recorded for the job again.
# ``lost`` is this server's own verdict; the rest are the API's terminal vocabulary.
FINAL_STATUSES = ("completed", "failed", "incomplete", "cancelled", "lost")


def is_final(job: ResearchJob) -> bool:
    """True when the job is observed for good: a final status, or its usage is already
    recorded (a state only a crash or a hand edit leaves on a non-final status)."""
    return job.status in FINAL_STATUSES or bool(job.usage_recorded)


def _gone(job_id: int | None = None) -> PerplexityError:
    named = f"Job {job_id}" if job_id is not None else "The job"
    return PerplexityError("not_found", f"{named} does not exist in this project.")


async def insert_job(session: AsyncSession, project_id: int, values: dict[str, Any]) -> ResearchJob:
    """Insert a job row (``values`` are column values) and return it with its id."""
    job = ResearchJob(project_id=project_id, **values)
    session.add(job)
    await session.flush()
    return job


async def load_job(session: AsyncSession, project_id: int, job_id: int) -> ResearchJob:
    """The job, scoped to its project: another project's job, or none, is ``not_found``."""
    job = (
        await session.execute(
            select(ResearchJob).where(
                ResearchJob.id == job_id, ResearchJob.project_id == project_id
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise _gone(job_id)
    return job


async def update_job(
    session: AsyncSession, project_id: int, job_id: int, values: dict[str, Any]
) -> ResearchJob:
    """Set ``values`` on the job and return the row as stored. ``not_found`` when it is gone."""
    result = await session.execute(
        update(ResearchJob)
        .where(ResearchJob.id == job_id, ResearchJob.project_id == project_id)
        .values(**values)
    )
    if result.rowcount == 0:
        raise _gone(job_id)
    job = await load_job(session, project_id, job_id)
    await session.refresh(job)  # the UPDATE bypassed the identity map
    return job


async def list_jobs(
    session: AsyncSession, project_id: int, limit: int
) -> tuple[list[ResearchJob], int]:
    """The project's jobs, newest first (highest id), at most ``limit``, and the total."""
    jobs = (
        (
            await session.execute(
                select(ResearchJob)
                .where(ResearchJob.project_id == project_id)
                .order_by(ResearchJob.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    total = (
        await session.execute(
            select(func.count())
            .select_from(ResearchJob)
            .where(ResearchJob.project_id == project_id)
        )
    ).scalar_one()
    return list(jobs), total


async def refresh_candidates(
    session: AsyncSession, project_id: int, limit: int
) -> tuple[list[int], int]:
    """Ids of the project's non-final jobs for a refresh: ``last_checked_at`` ascending, never
    checked first, ties by id ascending, at most ``limit``; and how many non-final jobs exist
    (design D7)."""
    running = (ResearchJob.project_id == project_id) & ResearchJob.status.not_in(FINAL_STATUSES)
    ids = (
        (
            await session.execute(
                select(ResearchJob.id)
                .where(running)
                .order_by(
                    ResearchJob.last_checked_at.is_not(None),  # False (never checked) sorts first
                    ResearchJob.last_checked_at.asc(),
                    ResearchJob.id.asc(),
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    total = (
        await session.execute(select(func.count()).select_from(ResearchJob).where(running))
    ).scalar_one()
    return list(ids), total

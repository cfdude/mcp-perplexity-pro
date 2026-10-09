"""``perplexity_projects``: list and delete projects (local-storage spec)."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.jobs import count_running
from mcp_perplexity_pro.storage.projects import (
    delete_project,
    list_projects,
    validate_project_name,
)
from mcp_perplexity_pro.storage.session import unit_of_work


class ProjectInfo(BaseModel):
    name: Annotated[str, Field(description="Project name")]
    created_at: Annotated[datetime, Field(description="When the project was created (UTC)")]


class ProjectsResult(BaseModel):
    action: Annotated[Literal["list", "delete"], Field(description="The action that ran")]
    projects: Annotated[
        list[ProjectInfo] | None, Field(description="All projects (list only; null for delete)")
    ] = None
    project: Annotated[
        str | None, Field(description="The deleted project's name (delete only)")
    ] = None
    rows_removed: Annotated[
        int | None,
        Field(
            description="Rows removed from tables that reference the project directly; "
            "deeper rows go by cascade and are not counted (delete only)"
        ),
    ] = None
    rows_retained: Annotated[
        int | None,
        Field(
            description="Retained records (spend history) detached from the project and kept "
            "(delete only; null for list)"
        ),
    ] = None
    running_jobs: Annotated[
        int | None,
        Field(
            description="Research jobs of the project that had not finished when it was deleted "
            "(delete only): their spend is never recorded and the provider keeps billing them "
            "until they end"
        ),
    ] = None


def _running_warning(count: int) -> str:
    return (
        f"{count} research job(s) in this project are still running at the provider. Deleting "
        "the project drops their records, their spend will never be recorded, and the provider "
        "keeps billing them until they end: cancel them first with perplexity_jobs cancel."
    )


def render(result: ProjectsResult) -> str:
    if result.action == "delete":
        text = (
            f"Deleted project {result.project!r}: {result.rows_removed} row(s) removed, "
            f"{result.rows_retained} retained record(s) kept (spend history stays reportable "
            "by project name)."
        )
        if result.running_jobs:
            text += f" Warning: {_running_warning(result.running_jobs)}"
        return text
    projects = result.projects or []
    if not projects:
        return "No projects yet."
    lines = [f"{len(projects)} project(s):"]
    lines.extend(f"{p.name} (created {p.created_at.isoformat()})" for p in projects)
    return "\n".join(lines)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def register(server: FastMCP) -> None:
    @server.tool(
        name="perplexity_projects",
        output_schema=ProjectsResult.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    )
    async def perplexity_projects(
        ctx: Context,
        action: Annotated[
            Literal["list", "delete"],
            Field(
                description="list: show all projects; delete: remove one project and its stored "
                "records (spend history is kept)"
            ),
        ],
        project: Annotated[str | None, Field(description="Project name (delete only)")] = None,
        confirm: Annotated[
            bool, Field(description="Must be true for delete; deletion cannot be undone")
        ] = False,
    ) -> ToolResult:
        """List the server's projects, or permanently delete one with its stored records.

        Spend history (usage events) is not deleted: it is kept, detached from the project, and
        stays reportable by the project's name. Neither action creates a project."""
        engine = ctx.lifespan_context.engine
        if action == "list":
            async with unit_of_work(engine, write=False) as session:
                rows = await list_projects(session)
            result = ProjectsResult(
                action="list",
                projects=[ProjectInfo(name=p.name, created_at=_utc(p.created_at)) for p in rows],
            )
        else:
            if project is None:
                raise PerplexityError("invalid_request", "delete needs a 'project' name.")
            validate_project_name(project)
            if confirm is not True:
                async with unit_of_work(engine, write=False) as session:
                    running = await count_running(session, project)
                raise PerplexityError(
                    "confirmation_required",
                    f"Deleting project {project!r} removes the project and its stored records and "
                    "cannot be undone; spend history is kept."
                    + (f" {_running_warning(running)}" if running else "")
                    + " Call again with confirm=true.",
                )
            async with unit_of_work(engine) as session:
                running = await count_running(session, project)
                outcome = await delete_project(session, project)
                if outcome is None:
                    raise PerplexityError("not_found", f"No project named {project!r}.")
            removed, retained = outcome
            result = ProjectsResult(
                action="delete",
                project=project,
                rows_removed=removed,
                rows_retained=retained,
                running_jobs=running,
            )
        return ToolResult(content=render(result), structured_content=result.model_dump(mode="json"))

"""``perplexity_projects``: list and delete projects (local-storage spec)."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_perplexity_pro.errors import PerplexityError
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


def render(result: ProjectsResult) -> str:
    if result.action == "delete":
        return f"Deleted project {result.project!r} and {result.rows_removed} row(s) it owned."
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
            Field(description="list: show all projects; delete: remove one project and its data"),
        ],
        project: Annotated[str | None, Field(description="Project name (delete only)")] = None,
        confirm: Annotated[
            bool, Field(description="Must be true for delete; deletion cannot be undone")
        ] = False,
    ) -> ToolResult:
        """List the server's projects, or permanently delete one with everything stored in it.

        Neither action creates a project."""
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
                raise PerplexityError(
                    "confirmation_required",
                    f"Deleting project {project!r} removes all its data and cannot be undone; "
                    "call again with confirm=true.",
                )
            async with unit_of_work(engine) as session:
                removed = await delete_project(session, project)
                if removed is None:
                    raise PerplexityError("not_found", f"No project named {project!r}.")
            result = ProjectsResult(action="delete", project=project, rows_removed=removed)
        return ToolResult(content=render(result), structured_content=result.model_dump(mode="json"))

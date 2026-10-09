"""``perplexity_usage``: a read-only spend report over the recorded usage events."""

import re
from datetime import date
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.projects import validate_project_name
from mcp_perplexity_pro.storage.session import unit_of_work
from mcp_perplexity_pro.usage import format_usd
from mcp_perplexity_pro.usage_report import Measures, Report, usage_report

TOOL = "perplexity_usage"
GroupBy = Literal["tool", "api", "model", "project", "day"]
MAX_LIMIT = 200
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class MeasuresInfo(BaseModel):
    calls: Annotated[int, Field(description="Recorded upstream calls, successes and errors")]
    errors: Annotated[int, Field(description="Calls whose status is not ok")]
    input_tokens: Annotated[int, Field(description="Input tokens (an unknown count adds 0)")]
    output_tokens: Annotated[int, Field(description="Output tokens (an unknown count adds 0)")]
    total_tokens: Annotated[int, Field(description="Total tokens (an unknown count adds 0)")]
    cost_nano_usd: Annotated[
        int, Field(description="Cost in nano-USD (10^-9 USD), an exact integer; a lower bound")
    ]
    cost_usd: Annotated[str, Field(description="The same cost as an exact decimal USD string")]
    calls_cost_computed: Annotated[
        int, Field(description="Calls whose cost the server computed from documented prices")
    ]
    calls_cost_unknown: Annotated[
        int, Field(description="Calls with no known cost (source none), errors included")
    ]


class GroupInfo(MeasuresInfo):
    key: Annotated[str, Field(description="The group's value; (none) when the event had none")]


class UsageResult(BaseModel):
    totals: Annotated[MeasuresInfo, Field(description="Over every matching call, ignoring limit")]
    group_by: Annotated[GroupBy, Field(description="The grouping that was applied")]
    groups: Annotated[list[GroupInfo], Field(description="At most `limit` groups")]
    groups_total: Annotated[int, Field(description="How many groups matched in all")]
    groups_truncated: Annotated[bool, Field(description="True when groups were cut by `limit`")]
    project: Annotated[str | None, Field(description="The project filter, if any")] = None
    since: Annotated[str | None, Field(description="The first UTC day included, if any")] = None
    until: Annotated[str | None, Field(description="The last UTC day included, if any")] = None
    limit: Annotated[int, Field(description="The group limit that was applied")]


def _measures(m: Measures) -> dict:
    return {**vars(m), "cost_usd": format_usd(m.cost_nano_usd)}


def _day(name: str, value: str | None) -> date | None:
    """A strict ``YYYY-MM-DD`` UTC day, else ``invalid_request`` (never ``internal_error``)."""
    if value is None:
        return None
    try:
        if not _DATE.fullmatch(value):
            raise ValueError
        parsed = date.fromisoformat(value)
    except ValueError:
        raise PerplexityError(
            "invalid_request", f"{name} must be a date written YYYY-MM-DD (UTC), got {value!r}."
        ) from None
    if name == "until" and parsed == date.max:
        raise PerplexityError(
            "invalid_request",
            "until 9999-12-31 is not allowed: the end of that day cannot be used.",
        )
    return parsed


def build_result(
    report: Report, project: str | None, since: str | None, until: str | None, limit: int
) -> UsageResult:
    return UsageResult(
        totals=MeasuresInfo(**_measures(report.totals)),
        group_by=report.group_by,
        groups=[GroupInfo(key=g.key, **_measures(g.measures)) for g in report.groups],
        groups_total=report.groups_total,
        groups_truncated=report.groups_truncated,
        project=project,
        since=since,
        until=until,
        limit=limit,
    )


def render(result: UsageResult) -> str:
    """A small fixed plain-text table: a totals line, then one row per group."""
    t = result.totals
    scope = [f"project {result.project}"] if result.project else []
    if result.since or result.until:
        scope.append(f"{result.since or '...'} to {result.until or '...'} (UTC)")
    lines = [
        f"Usage{' for ' + ', '.join(scope) if scope else ''}: {t.calls} call(s), "
        f"{t.errors} error(s), {t.total_tokens} token(s), cost {t.cost_usd} USD "
        f"({t.cost_nano_usd} nano-USD)."
    ]
    if t.calls:
        lines.append(
            "The cost is a lower bound: error calls count cost 0 and may have been billed; "
            f"{t.calls_cost_unknown} call(s) have no known cost and {t.calls_cost_computed} "
            "cost(s) were computed from documented prices."
        )
    if result.groups:
        lines.append(f"By {result.group_by}: key | calls | errors | tokens | cost USD")
        lines.extend(
            f"{g.key} | {g.calls} | {g.errors} | {g.total_tokens} | {g.cost_usd}"
            for g in result.groups
        )
    if result.groups_truncated:
        lines.append(
            f"Showing {len(result.groups)} of {result.groups_total} groups "
            f"(limit {result.limit}); the totals cover all of them."
        )
    return "\n".join(lines)


def register(server: FastMCP) -> None:
    @server.tool(
        name=TOOL,
        output_schema=UsageResult.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    async def perplexity_usage(
        ctx: Context,
        project: Annotated[
            str | None,
            Field(description="Only this project's calls, matched by name (default: all projects)"),
        ] = None,
        since: Annotated[
            str | None,
            Field(description="First UTC day to include, written YYYY-MM-DD (default: no start)"),
        ] = None,
        until: Annotated[
            str | None,
            Field(description="Last UTC day to include, written YYYY-MM-DD (default: no end)"),
        ] = None,
        group_by: Annotated[
            GroupBy, Field(description="Group by tool, api, model, project or day")
        ] = "tool",
        limit: Annotated[
            int,
            Field(description=f"Most groups to return, 1 to {MAX_LIMIT} (day keeps the latest)"),
        ] = 20,
    ) -> ToolResult:
        """Report what recorded upstream Perplexity calls cost: exact totals over every matching
        call plus one grouping, filtered by project and UTC date range. Read-only.

        The cost is a lower bound: error calls count cost 0 and may have been billed.
        calls_cost_unknown says how many calls have no known cost. Unknown token counts add 0.
        Projects are matched by the name recorded with each call, so a deleted project still
        reports. The Agent tools (ask, chat, research) record their calls; nothing is recorded
        by a tool that does not make costed calls."""
        if project is not None:
            validate_project_name(project)
        first, last = _day("since", since), _day("until", until)
        if first is not None and last is not None and first > last:
            raise PerplexityError("invalid_request", "since must not be after until.")
        if isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
            raise PerplexityError("invalid_request", f"limit must be between 1 and {MAX_LIMIT}.")
        async with unit_of_work(ctx.lifespan_context.engine, write=False) as session:
            report = await usage_report(
                session, project=project, since=first, until=last, group_by=group_by, limit=limit
            )
        result = build_result(report, project, since, until, limit)
        return ToolResult(content=render(result), structured_content=result.model_dump(mode="json"))

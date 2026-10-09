"""Read-only spend report over ``usage_events`` (usage-reporting spec; design D10).

Every figure is an exact integer ``SUM`` or ``COUNT`` computed in SQL. The totals come from a
query of their own over ALL matching rows, so they never depend on the group ``limit``. The
grouping column is chosen from a fixed whitelist and never built from caller text; every
caller-supplied value is a bound parameter. Nothing here writes, and the project filter matches
``project_name`` without looking the project up, so a deleted or never-created project reports
normally and no project is created.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

NONE_KEY = "(none)"

# group_by -> the SQL expression it groups on. A fixed whitelist: an unknown key is refused, and
# no caller text is ever placed in SQL.
GROUP_EXPRESSIONS = {
    "tool": "tool",
    "api": "api",
    "model": "model",
    "project": "project_name",
    "day": "date(created_at)",
}

_MEASURES = """
    COUNT(*) AS calls,
    COALESCE(SUM(status != 'ok'), 0) AS errors,
    COALESCE(SUM(input_tokens), 0) AS input_tokens,
    COALESCE(SUM(output_tokens), 0) AS output_tokens,
    COALESCE(SUM(total_tokens), 0) AS total_tokens,
    COALESCE(SUM(cost_nano_usd), 0) AS cost_nano_usd,
    COALESCE(SUM(cost_source = 'computed'), 0) AS calls_cost_computed,
    COALESCE(SUM(cost_source = 'none'), 0) AS calls_cost_unknown
"""


@dataclass(frozen=True)
class Measures:
    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_nano_usd: int
    calls_cost_computed: int
    calls_cost_unknown: int


@dataclass(frozen=True)
class Group:
    key: str
    measures: Measures


@dataclass(frozen=True)
class Report:
    totals: Measures
    group_by: str
    groups: list[Group]
    groups_total: int
    groups_truncated: bool


def _where(project: str | None, since: date | None, until: date | None) -> tuple[str, dict]:
    """The filter clause and its bound parameters; ``until`` is inclusive of its whole UTC day."""
    clauses, params = [], {}
    if project is not None:
        clauses.append("project_name = :project")
        params["project"] = project
    if since is not None:
        clauses.append("created_at >= :since")
        params["since"] = f"{since.isoformat()} 00:00:00"
    if until is not None:
        try:
            after = until + timedelta(days=1)
        except OverflowError:
            raise ValueError("until has no representable end of day") from None
        clauses.append("created_at < :until")
        params["until"] = f"{after.isoformat()} 00:00:00"
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _measures(row) -> Measures:
    return Measures(*(int(v) for v in row))


async def usage_report(
    session: AsyncSession,
    *,
    project: str | None = None,
    since: date | None = None,
    until: date | None = None,
    group_by: str = "tool",
    limit: int = 20,
) -> Report:
    """Totals over every matching event plus the top ``limit`` groups of ``group_by``.

    Groups are ordered by cost descending then key; ``day`` selects the latest ``limit`` days
    and returns them ascending. Raises ``ValueError`` for an unknown ``group_by``, a ``limit``
    below 1 or an ``until`` whose end of day cannot be represented.
    """
    expression = GROUP_EXPRESSIONS.get(group_by) if isinstance(group_by, str) else None
    if expression is None:
        raise ValueError(f"unknown group_by {group_by!r}")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    where, params = _where(project, since, until)
    key = f"COALESCE({expression}, '{NONE_KEY}')"  # both fragments are fixed text, not input

    totals = _measures(
        (await session.execute(text(f"SELECT {_MEASURES} FROM usage_events{where}"), params)).one()
    )
    groups_total = (
        await session.execute(
            text(f"SELECT COUNT(*) FROM (SELECT 1 FROM usage_events{where} GROUP BY {key})"),
            params,
        )
    ).scalar_one()
    order = "key DESC" if group_by == "day" else "cost_nano_usd DESC, key ASC"
    rows = (
        await session.execute(
            text(
                f"SELECT {key} AS key, {_MEASURES} FROM usage_events{where} "
                f"GROUP BY {key} ORDER BY {order} LIMIT :limit"
            ),
            {**params, "limit": limit},
        )
    ).all()
    groups = [Group(row[0], _measures(row[1:])) for row in rows]
    if group_by == "day":
        groups.sort(key=lambda g: g.key)
    return Report(totals, group_by, groups, groups_total, groups_total > len(groups))

"""Project-name rules and the shared get-or-create operation.

Every tool that stores records resolves its project through ``get_or_create_project``;
``perplexity_projects`` and tools without a project argument never call it.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from sqlalchemy import Connection, delete, select, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.models import Project

DEFAULT_PROJECT = "default"
MAX_NAME_LENGTH = 64
_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}", re.ASCII)
# A name shaped like an API key (``pplx-`` plus 20 or more key characters) is refused: the name
# is stored, listed and echoed in errors, and a pasted key must never end up there.
_KEY_SHAPED_NAME = re.compile(r"pplx-[A-Za-z0-9_-]{20,}")


def validate_project_name(name: str) -> str:
    """Return ``name`` if valid, else raise ``PerplexityError`` (``invalid_request``)."""
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise PerplexityError(
            "invalid_request",
            f"Invalid project name {name!r}: use 1-{MAX_NAME_LENGTH} ASCII letters, digits, "
            "'-', '_' or '.'.",
        )
    if name.startswith("."):  # also rejects '.' and '..'
        raise PerplexityError(
            "invalid_request", f"Invalid project name {name!r}: must not begin with '.'."
        )
    if _KEY_SHAPED_NAME.search(name):
        raise PerplexityError(
            "invalid_request",
            "Invalid project name: it looks like an API key. Choose a descriptive name.",
        )
    return name


async def get_or_create_project(session: AsyncSession, name: str | None = None) -> Project:
    """Resolve ``name`` (default ``default``), creating the project the first time it is named.

    The insert is an upsert (``ON CONFLICT DO NOTHING``), so concurrent first creates cannot
    violate the unique constraint; run it inside a write unit of work.
    """
    name = validate_project_name(DEFAULT_PROJECT if name is None else name)
    await session.execute(insert(Project).values(name=name).on_conflict_do_nothing(["name"]))
    return (await session.execute(select(Project).where(Project.name == name))).scalar_one()


async def list_projects(session: AsyncSession) -> list[Project]:
    """Every project, oldest first. Reads only: it never creates a project."""
    return list((await session.execute(select(Project).order_by(Project.id))).scalars())


# Project-scoped tables are found by introspection, not by a registry anyone must edit. The
# convention for a table that later epics add: give it a column with a foreign key to
# ``projects.id``, and choose its fate by how the key's delete rule is declared:
#
# * ``ON DELETE CASCADE`` (or no action): an ordinary table. ``delete_project`` clears its rows
#   and counts them in ``rows_removed``.
# * ``ON DELETE SET NULL``: a RETAINED table (spend history is the first). ``delete_project``
#   detaches its rows with an explicit ``UPDATE ... SET <col> = NULL`` and counts them in
#   ``rows_retained``. Such a table must keep its own copy of the project name (a column the
#   migration adds), because the reference is gone afterwards.
#
# Neither case needs a change here. The delete rule is read with ``PRAGMA foreign_key_list``
# because SQLAlchemy's inspector omits it on SQLite. Rows two hops away (a table whose foreign
# key points at a project-scoped table, not at ``projects``) are handled by their own
# ``ON DELETE`` rule and are NOT in either count.
class ScopedTable(NamedTuple):
    table: str
    column: str
    retained: bool  # True when the key is declared ON DELETE SET NULL


def _quote_sqlite(name: str) -> str:
    """Double-quote an identifier for a PRAGMA (which takes no bound parameter)."""
    return '"' + name.replace('"', '""') + '"'


def _scoped_tables(sync_conn: Connection) -> list[ScopedTable]:
    # Table names come from sqlite_master and are quoted, never interpolated raw.
    names = sync_conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).scalars()
    projects_pk = [
        row[1]
        for row in sync_conn.exec_driver_sql(
            f"PRAGMA table_info({_quote_sqlite(Project.__tablename__)})"
        )
        if row[5]
    ]
    found = []
    for table in list(names):
        # columns: id, seq, table, from, to, on_update, on_delete, match
        keys: dict[int, list] = {}
        for row in sync_conn.exec_driver_sql(f"PRAGMA foreign_key_list({_quote_sqlite(table)})"):
            keys.setdefault(row[0], []).append(row)
        for rows in keys.values():
            if len(rows) != 1 or rows[0][2].lower() != Project.__tablename__:
                continue
            _, _, _, column, target, _, on_delete, _ = rows[0]
            # ``REFERENCES projects`` without a column means the parent's primary key.
            if (target is None and projects_pk != ["id"]) or target not in (None, "id"):
                continue
            found.append(ScopedTable(table, column, on_delete.upper() == "SET NULL"))
    return found


async def delete_project(session: AsyncSession, name: str) -> tuple[int, int] | None:
    """Delete project ``name`` inside the caller's unit of work.

    Returns ``(removed, detached)``: rows removed from ordinary project-scoped tables and rows
    detached (reference set to NULL) in retained ones, or ``None`` when no such project exists
    (nothing is created). Ordinary rows are deleted and retained rows detached first, the
    project last, so the caller's single transaction either does everything or, on any
    failure, nothing.
    """
    project = (
        await session.execute(select(Project).where(Project.name == name))
    ).scalar_one_or_none()
    if project is None:
        return None
    conn = await session.connection()
    scoped = await conn.run_sync(_scoped_tables)
    quote = conn.dialect.identifier_preparer.quote
    removed = detached = 0
    for table, column, retained in scoped:
        if retained:
            statement = f"UPDATE {quote(table)} SET {quote(column)} = NULL"
        else:
            statement = f"DELETE FROM {quote(table)}"
        result = await session.execute(
            text(f"{statement} WHERE {quote(column)} = :id"), {"id": project.id}
        )
        if retained:
            detached += result.rowcount
        else:
            removed += result.rowcount
    await session.execute(delete(Project).where(Project.id == project.id))
    return removed, detached

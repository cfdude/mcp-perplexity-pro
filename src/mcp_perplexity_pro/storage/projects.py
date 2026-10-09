"""Project-name rules and the shared get-or-create operation.

Every tool that stores records resolves its project through ``get_or_create_project``;
``perplexity_projects`` and tools without a project argument never call it.
"""

from __future__ import annotations

import re

from sqlalchemy import Connection, delete, inspect, select, text
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
# ``projects.id`` (declare ``ON DELETE CASCADE`` so SQLite also clears it on its own). Every
# such table is cleared and counted by ``delete_project``, which therefore needs no change when
# a table is added. Rows two hops away (a table whose foreign key points at a project-scoped
# table, not at ``projects``) are removed by their own ``ON DELETE CASCADE`` and are NOT in the
# reported count.
def _scoped_tables(sync_conn: Connection) -> list[tuple[str, str]]:
    insp = inspect(sync_conn)
    found = []
    for table in sorted(insp.get_table_names()):
        for fk in insp.get_foreign_keys(table):
            if fk["referred_table"] == Project.__tablename__ and fk["referred_columns"] == ["id"]:
                found.extend((table, column) for column in fk["constrained_columns"])
    return found


async def delete_project(session: AsyncSession, name: str) -> int | None:
    """Delete project ``name`` and its rows inside the caller's unit of work.

    Returns the number of rows removed from project-scoped tables, or ``None`` when no such
    project exists (nothing is created). Child rows are deleted first and the project last, so
    the caller's single transaction either removes everything or, on any failure, nothing.
    """
    project = (
        await session.execute(select(Project).where(Project.name == name))
    ).scalar_one_or_none()
    if project is None:
        return None
    conn = await session.connection()
    scoped = await conn.run_sync(_scoped_tables)
    quote = conn.dialect.identifier_preparer.quote
    removed = 0
    for table, column in scoped:
        result = await session.execute(
            text(f"DELETE FROM {quote(table)} WHERE {quote(column)} = :id"), {"id": project.id}
        )
        removed += result.rowcount
    await session.execute(delete(Project).where(Project.id == project.id))
    return removed

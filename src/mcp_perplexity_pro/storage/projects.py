"""Project-name rules and the shared get-or-create operation.

Every tool that stores records resolves its project through ``get_or_create_project``;
``perplexity_projects`` and tools without a project argument never call it.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.models import Project

DEFAULT_PROJECT = "default"
MAX_NAME_LENGTH = 64
_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}", re.ASCII)


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
    return name


async def get_or_create_project(session: AsyncSession, name: str | None = None) -> Project:
    """Resolve ``name`` (default ``default``), creating the project the first time it is named.

    The insert is an upsert (``ON CONFLICT DO NOTHING``), so concurrent first creates cannot
    violate the unique constraint; run it inside a write unit of work.
    """
    name = validate_project_name(DEFAULT_PROJECT if name is None else name)
    await session.execute(insert(Project).values(name=name).on_conflict_do_nothing(["name"]))
    return (await session.execute(select(Project).where(Project.name == name))).scalar_one()

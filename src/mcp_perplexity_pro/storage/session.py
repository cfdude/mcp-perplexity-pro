"""Unit of work: one ``AsyncSession`` per tool call (design D10).

``unit_of_work`` is an ``@asynccontextmanager`` function on purpose: FastMCP manages a
context-manager dependency but would hand a bare async generator to the tool as an object.
The session commits when the block returns and rolls back on *any* exception, so a call that
fails after writing leaves nothing behind.

A write unit of work begins with ``BEGIN IMMEDIATE`` so the write lock is taken up front and
``busy_timeout`` applies. A lock that stays held past the timeout surfaces as a
``PerplexityError`` with category ``storage_busy``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.engine import BEGIN_OPTION

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_BUSY_MARKERS = ("database is locked", "database table is locked", "database is busy")


def is_busy_error(exc: BaseException) -> bool:
    """True for SQLite lock contention (``SQLITE_BUSY``/``SQLITE_LOCKED``) errors."""
    if not isinstance(exc, OperationalError):
        return False
    text = str(getattr(exc, "orig", exc)).lower()
    return any(marker in text for marker in _BUSY_MARKERS)


def storage_busy_error() -> PerplexityError:
    return PerplexityError(
        "storage_busy",
        "The local database is busy: another operation held the write lock longer than the "
        "configured busy timeout. Retry shortly.",
    )


@asynccontextmanager
async def unit_of_work(engine: AsyncEngine, *, write: bool = True) -> AsyncIterator[AsyncSession]:
    """Yield a session for one tool call; commit on return, roll back on any exception.

    ``write=True`` (default) starts the transaction with ``BEGIN IMMEDIATE``; pass
    ``write=False`` for a read-only call.
    """
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        if write:
            await session.connection(execution_options={BEGIN_OPTION: "IMMEDIATE"})
        yield session
        await session.commit()
    except BaseException as exc:
        await session.rollback()
        if is_busy_error(exc):
            raise storage_busy_error() from exc
        raise
    finally:
        await session.close()

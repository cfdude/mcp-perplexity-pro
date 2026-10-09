"""Task 5.4: concurrent writers and lock contention (local-storage 'Concurrent calls')."""

import asyncio
import sqlite3
import time

import pytest
from sqlalchemy import text

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.engine import create_engine_for, database_path
from mcp_perplexity_pro.storage.migrate import migrate
from mcp_perplexity_pro.storage.projects import get_or_create_project
from mcp_perplexity_pro.storage.session import unit_of_work

PARALLEL_CALLS = 20
BUSY_TIMEOUT = 5  # seconds; the parallel test is meaningless (and fails) when this is 0


async def _engine_with_notes(make_settings, busy_timeout):
    settings = make_settings(db_busy_timeout=busy_timeout)
    migrate(settings)
    engine = create_engine_for(settings)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, body TEXT NOT NULL, "
                "project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE)"
            )
        )
    return settings, engine


async def _write_note(engine, body, project="shared"):
    """TEST-ONLY writing tool."""
    async with unit_of_work(engine) as session:
        proj = await get_or_create_project(session, project)
        await session.execute(
            text("INSERT INTO notes (body, project_id) VALUES (:b, :p)"),
            {"b": body, "p": proj.id},
        )


async def test_twenty_parallel_writes_all_succeed_and_all_rows_exist(make_settings):
    _settings, engine = await _engine_with_notes(make_settings, BUSY_TIMEOUT)
    try:
        barrier = asyncio.Barrier(PARALLEL_CALLS)

        async def call(i):
            await barrier.wait()  # release every call at the same instant
            await _write_note(engine, f"note-{i}")  # all 20 first-create the same project

        results = await asyncio.gather(
            *(call(i) for i in range(PARALLEL_CALLS)), return_exceptions=True
        )
        assert [r for r in results if r is not None] == []  # none raised

        async with engine.connect() as conn:
            bodies = set((await conn.execute(text("SELECT body FROM notes"))).scalars())
            projects = (await conn.execute(text("SELECT count(*) FROM projects"))).scalar_one()
        assert bodies == {f"note-{i}" for i in range(PARALLEL_CALLS)}
        assert projects == 1  # the upsert let 20 concurrent first-creates share one row
    finally:
        await engine.dispose()


async def test_waiting_writer_reports_storage_busy_after_the_timeout(make_settings):
    settings, engine = await _engine_with_notes(make_settings, 0.3)
    holder = sqlite3.connect(database_path(settings.data_dir), timeout=0, isolation_level=None)
    try:
        holder.execute("BEGIN IMMEDIATE")  # a second connection holds the write lock
        start = time.monotonic()
        with pytest.raises(PerplexityError) as err:
            await _write_note(engine, "blocked")
        waited = time.monotonic() - start
        assert err.value.category == "storage_busy"
        # It waited for the busy timeout, then gave up. SQLite's busy handler may overshoot a
        # short timeout (about 1.5 s for 0.3 s here), so only the lower bound is exact.
        assert 0.25 <= waited < 10
        holder.execute("ROLLBACK")

        await _write_note(engine, "after release")  # the lock is free again: works
        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT body FROM notes"))).scalars().all()
        assert rows == ["after release"]  # the blocked call left nothing behind
    finally:
        holder.close()
        await engine.dispose()

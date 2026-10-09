"""Task 5.3: unit of work and project resolution (local-storage 'Project resolution',
'Project names', 'All-or-nothing tool calls')."""

import pytest
from sqlalchemy import text

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.projects import (
    DEFAULT_PROJECT,
    get_or_create_project,
    validate_project_name,
)
from mcp_perplexity_pro.storage.session import unit_of_work


async def write_note(engine, body, project=None, *, then_raise=None):
    """TEST-ONLY writing tool: resolve the project, store one note, optionally fail after."""
    async with unit_of_work(engine) as session:
        proj = await get_or_create_project(session, project)
        await session.execute(
            text("INSERT INTO notes (body, project_id) VALUES (:b, :p)"),
            {"b": body, "p": proj.id},
        )
        if then_raise:
            raise then_raise
        return proj.name


async def _scalar(engine, sql, **params):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar_one()


async def _project_names(engine):
    async with engine.connect() as conn:
        return sorted((await conn.execute(text("SELECT name FROM projects"))).scalars())


async def test_implicit_creation_of_a_named_project(storage_engine):
    assert await _project_names(storage_engine) == []
    assert await write_note(storage_engine, "hi", "alpha") == "alpha"
    assert await _project_names(storage_engine) == ["alpha"]
    assert await _scalar(storage_engine, "SELECT count(*) FROM notes") == 1


async def test_existing_project_is_reused_not_duplicated(storage_engine):
    await write_note(storage_engine, "one", "alpha")
    await write_note(storage_engine, "two", "alpha")
    assert await _project_names(storage_engine) == ["alpha"]
    assert await _scalar(storage_engine, "SELECT count(*) FROM notes") == 2


async def test_default_project_is_used_and_created_if_absent(storage_engine):
    assert DEFAULT_PROJECT == "default"
    assert await write_note(storage_engine, "hi") == "default"
    assert await _project_names(storage_engine) == ["default"]


@pytest.mark.parametrize("bad", ["../etc", ".hidden", ".", "..", "", "a/b", "with space", "ünï"])
async def test_invalid_names_fail_invalid_request_and_create_nothing(storage_engine, bad):
    with pytest.raises(PerplexityError) as err:
        await write_note(storage_engine, "x", bad)
    assert err.value.category == "invalid_request"
    assert await _project_names(storage_engine) == []
    assert await _scalar(storage_engine, "SELECT count(*) FROM notes") == 0


def test_name_length_and_charset_boundaries():
    assert validate_project_name("a" * 64) == "a" * 64
    assert validate_project_name("My-proj_1.2") == "My-proj_1.2"
    assert validate_project_name("a.") == "a."
    for bad in ("a" * 65, "line\nbreak", "tab\t", "trailing\n"):
        with pytest.raises(PerplexityError) as err:
            validate_project_name(bad)
        assert err.value.category == "invalid_request"


async def test_names_are_case_sensitive(storage_engine):
    await write_note(storage_engine, "a", "Alpha")
    await write_note(storage_engine, "b", "alpha")
    assert await _project_names(storage_engine) == ["Alpha", "alpha"]


async def test_unit_of_work_that_writes_then_raises_leaves_no_row(storage_engine):
    with pytest.raises(RuntimeError, match="after the write"):
        await write_note(
            storage_engine, "ghost", "gone", then_raise=RuntimeError("after the write")
        )
    assert await _scalar(storage_engine, "SELECT count(*) FROM notes") == 0
    assert await _project_names(storage_engine) == []  # the implicit project rolled back too


async def test_cancellation_also_rolls_back(storage_engine):
    import asyncio

    with pytest.raises(asyncio.CancelledError):
        await write_note(storage_engine, "ghost", "gone", then_raise=asyncio.CancelledError())
    assert await _scalar(storage_engine, "SELECT count(*) FROM notes") == 0


async def test_unit_of_work_is_a_context_manager_not_a_bare_generator():
    import inspect

    assert not inspect.isasyncgenfunction(unit_of_work)  # asynccontextmanager wraps it
    assert hasattr(unit_of_work(None), "__aenter__")


async def test_write_unit_of_work_begins_immediate(storage_engine):
    # While one write unit of work is open, a second cannot BEGIN IMMEDIATE (lock is held
    # from the start, before any statement) -- observed through the raw lock.
    import sqlite3

    async with unit_of_work(storage_engine) as session:
        await session.execute(text("SELECT 1"))
        other = sqlite3.connect(storage_engine.url.database, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
        finally:
            other.close()


async def test_deleting_a_project_cascades_to_children(storage_engine):
    await write_note(storage_engine, "x", "alpha")
    async with unit_of_work(storage_engine) as session:
        await session.execute(text("DELETE FROM projects WHERE name='alpha'"))
    assert await _scalar(storage_engine, "SELECT count(*) FROM notes") == 0


KEY_SHAPED = "pplx-" + "abcdefghijklmnopqrstuvwx"  # pplx- followed by 24 letters


def test_key_shaped_names_are_rejected():
    with pytest.raises(PerplexityError) as info:
        validate_project_name(KEY_SHAPED)
    assert info.value.category == "invalid_request"
    assert KEY_SHAPED not in str(info.value)  # the rejection must not echo the key shape
    validate_project_name("pplx-short")  # not key-shaped: fewer than 20 key characters


async def test_key_shaped_name_via_get_or_create_creates_nothing(storage_engine):
    with pytest.raises(PerplexityError) as info:
        await write_note(storage_engine, "x", KEY_SHAPED)
    assert info.value.category == "invalid_request"
    assert await _project_names(storage_engine) == []

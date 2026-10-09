"""Task 5.1: engine pragmas, owner-only directory, no writes outside the data directory."""

import os
import stat

import pytest
from sqlalchemy import text

from mcp_perplexity_pro.storage.engine import (
    StorageError,
    create_engine_for,
    database_path,
    prepare_data_dir,
)


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


async def _pragma(conn, name):
    return (await conn.execute(text(f"PRAGMA {name}"))).scalar_one()


async def test_pragmas_apply_to_every_pooled_connection(make_settings):
    engine = create_engine_for(make_settings(db_busy_timeout=2.5))
    try:
        # Two connections open at once are necessarily two distinct pooled connections.
        async with engine.connect() as first, engine.connect() as second:
            for conn in (first, second):
                assert str(await _pragma(conn, "journal_mode")).lower() == "wal"
                assert await _pragma(conn, "busy_timeout") == 2500
                assert await _pragma(conn, "foreign_keys") == 1
    finally:
        await engine.dispose()


async def test_first_start_creates_owner_only_directory_and_database(make_settings):
    settings = make_settings()
    assert not settings.data_dir.exists()
    engine = create_engine_for(settings)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
    assert settings.data_dir.is_dir()
    assert _mode(settings.data_dir) == 0o700
    assert _mode(database_path(settings.data_dir)) == 0o600


def test_nested_data_directory_is_created_owner_only(tmp_path):
    target = tmp_path / "a" / "b" / "data"
    prepare_data_dir(target)
    assert _mode(target) == 0o700


def test_existing_loose_directory_is_tightened(tmp_path):
    target = tmp_path / "loose"
    target.mkdir()
    target.chmod(0o755)
    prepare_data_dir(target)
    assert _mode(target) == 0o700


def test_existing_loose_database_file_is_tightened(tmp_path):
    db = database_path(tmp_path)
    db.write_bytes(b"")
    db.chmod(0o644)
    prepare_data_dir(tmp_path)
    assert _mode(db) == 0o600


def test_directory_that_cannot_be_secured_fails_naming_it(tmp_path, monkeypatch):
    target = tmp_path / "stuck"
    target.mkdir()
    target.chmod(0o755)

    def refuse(self, mode):
        raise PermissionError("not permitted")

    monkeypatch.setattr(type(target), "chmod", refuse)
    with pytest.raises(StorageError, match="stuck"):
        prepare_data_dir(target)


def test_path_that_is_a_file_fails_naming_it(tmp_path):
    target = tmp_path / "file"
    target.write_text("x")
    with pytest.raises(StorageError, match="file"):
        prepare_data_dir(target)


async def test_nothing_is_written_to_the_working_directory(make_settings, tmp_path, monkeypatch):
    cwd = tmp_path / "project-repo"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    settings = make_settings(data_dir=tmp_path / "elsewhere")
    engine = create_engine_for(settings)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE t (x)"))
            await conn.execute(text("INSERT INTO t VALUES (1)"))
    finally:
        await engine.dispose()
    assert os.listdir(cwd) == []
    assert database_path(settings.data_dir).exists()

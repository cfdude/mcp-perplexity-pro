"""Task 1.3: the ``usage_events`` table, its migration ``0002`` and its fit with deletion
(usage-recording "Usage events", local-storage "Retained records")."""

import shutil
import sqlite3
import subprocess
import zipfile
from pathlib import Path

import pytest

from mcp_perplexity_pro.storage.engine import create_engine_for, database_path
from mcp_perplexity_pro.storage.migrate import (
    MIGRATIONS_DIR,
    backup_path,
    current_revision,
    downgrade,
    head_revision,
    migrate,
)
from mcp_perplexity_pro.storage.models import UsageEvent
from mcp_perplexity_pro.storage.projects import delete_project, get_or_create_project
from mcp_perplexity_pro.storage.session import unit_of_work

ROOT = Path(__file__).resolve().parent.parent

# column -> NOT NULL? (design D1; the primary key is checked separately)
EXPECTED_COLUMNS = {
    "id": True,
    "created_at": True,
    "tool": True,
    "api": True,
    "status": True,
    "latency_ms": False,
    "model": False,
    "preset": False,
    "request_id": False,
    "project_id": False,
    "project_name": False,
    "input_tokens": False,
    "output_tokens": False,
    "total_tokens": False,
    "cached_tokens": False,
    "cache_creation_tokens": False,
    "cache_read_tokens": False,
    "reasoning_tokens": False,
    "cost_nano_usd": True,
    "cost_source": True,
    "currency": True,
    "input_cost_nano": False,
    "output_cost_nano": False,
    "cache_read_cost_nano": False,
    "cache_creation_cost_nano": False,
    "tool_calls_cost_nano": False,
    "price_table": False,
    "tool_calls_json": False,
    "usage_json": False,
}

INSERT = (
    "INSERT INTO usage_events (created_at, tool, api, status, cost_source, project_id, "
    "project_name, request_id) VALUES ('2026-10-09 12:00:00.000000', 't', 'agent', :status, "
    "'reported', :pid, :pname, :rid)"
)


def table_info(db, table="usage_events"):
    with sqlite3.connect(db) as conn:
        return conn.execute(f'PRAGMA table_info("{table}")').fetchall()


def tables(db):
    with sqlite3.connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def sql_exec(db, sql, **params):
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(sql, params)


def sql_all(db, sql, **params):
    with sqlite3.connect(db) as conn:
        return conn.execute(sql, params).fetchall()


@pytest.fixture
def settings(make_settings):
    return make_settings()


@pytest.fixture
def db(settings):
    return database_path(settings.data_dir)


@pytest.fixture
def only_0001(tmp_path):
    """A scratch migrations directory holding revision 0001 only."""
    target = tmp_path / "only-0001"
    shutil.copytree(MIGRATIONS_DIR, target, ignore=shutil.ignore_patterns("__pycache__"))
    for extra in (target / "versions").glob("000[2-9]_*.py"):
        extra.unlink()
    return target


def test_fresh_database_reaches_0002(settings, db):
    result = migrate(settings)
    assert result.applied == ("0001", "0002")
    assert current_revision(db) == head_revision() == "0002"
    assert "usage_events" in tables(db)


def test_a_0001_database_upgrades_keeping_projects_and_backing_up(settings, db, only_0001):
    migrate(settings, script_location=only_0001)
    for name in ("alpha", "beta"):
        sql_exec(db, "INSERT INTO projects (name) VALUES (:n)", n=name)
    before = sql_all(db, "SELECT id, name, created_at FROM projects ORDER BY id")
    result = migrate(settings)
    assert result.applied == ("0002",)
    assert sql_all(db, "SELECT id, name, created_at FROM projects ORDER BY id") == before
    assert sql_all(db, "SELECT count(*) FROM usage_events") == [(0,)]
    backup = backup_path(settings.data_dir, "0001")
    assert result.backup == backup and backup.exists()
    assert "usage_events" not in tables(backup)


def test_upgrade_downgrade_upgrade_and_downgrade_keeps_projects(settings, db):
    migrate(settings)
    sql_exec(db, "INSERT INTO projects (name) VALUES ('kept')")
    pid = sql_all(db, "SELECT id FROM projects")[0][0]
    sql_exec(db, INSERT, status="ok", pid=pid, pname="kept", rid="r1")

    result = downgrade(settings)
    assert result.applied == ("0002",)
    assert current_revision(db) == "0001"
    assert "usage_events" not in tables(db)
    assert sql_all(db, "SELECT name FROM projects") == [("kept",)]  # projects and rows intact
    leftovers = sql_all(db, "SELECT name FROM sqlite_master WHERE name LIKE '%usage_events%'")
    assert leftovers == []  # its indexes went with it

    migrate(settings)
    assert current_revision(db) == "0002"
    assert sql_all(db, "SELECT count(*) FROM usage_events") == [(0,)]


def test_every_column_name_and_nullability_matches_design_d1(settings, db):
    migrate(settings)
    info = table_info(db)
    assert {row[1]: bool(row[3]) for row in info} == EXPECTED_COLUMNS
    assert [row[1] for row in info if row[5]] == ["id"]  # the primary key
    defaults = {row[1]: row[4] for row in info if row[4] is not None}
    assert defaults == {"cost_nano_usd": "0", "currency": "'USD'"}


def test_the_project_key_is_set_null_and_a_name_is_kept_beside_it(settings, db):
    """The retained-table convention is only a convention: this is its enforcement."""
    migrate(settings)
    # PRAGMA columns: id, seq, table, from, to, on_update, on_delete, match
    keys = sql_all(db, 'PRAGMA foreign_key_list("usage_events")')
    assert [(k[2], k[3], k[4], k[6]) for k in keys] == [
        ("projects", "project_id", "id", "SET NULL")
    ]
    assert "project_name" in {row[1] for row in table_info(db)}


def test_the_orm_model_matches_the_migrated_table(settings, db):
    migrate(settings)
    migrated = {row[1]: bool(row[3]) for row in table_info(db)}
    model = {c.name: not c.nullable for c in UsageEvent.__table__.columns}
    assert model == migrated
    assert UsageEvent.__tablename__ == "usage_events"


def test_indexes_exist_and_the_dedupe_index_is_partial(settings, db):
    migrate(settings)
    indexes = dict(
        sql_all(
            db, "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='usage_events'"
        )
    )
    assert {"ix_usage_events_created_at", "ix_usage_events_project_name"} <= set(indexes)
    dedupe = next(sql for name, sql in indexes.items() if sql and "UNIQUE" in sql.upper())
    assert "(api, request_id)" in dedupe.replace('"', "")
    assert "request_id IS NOT NULL AND status = 'ok'" in dedupe

    sql_exec(db, INSERT, status="ok", pid=None, pname=None, rid="same")
    with pytest.raises(sqlite3.IntegrityError):
        sql_exec(db, INSERT, status="ok", pid=None, pname=None, rid="same")
    # outside the partial index: failures, and rows without an id, are not deduplicated
    sql_exec(db, INSERT, status="rate_limited", pid=None, pname=None, rid="same")
    sql_exec(db, INSERT, status="rate_limited", pid=None, pname=None, rid="same")
    sql_exec(db, INSERT, status="ok", pid=None, pname=None, rid=None)
    sql_exec(db, INSERT, status="ok", pid=None, pname=None, rid=None)


async def test_deleting_a_project_detaches_its_events_by_name(make_settings):
    settings = make_settings()
    migrate(settings)
    db = database_path(settings.data_dir)
    engine = create_engine_for(settings)
    try:
        async with unit_of_work(engine) as session:
            project = await get_or_create_project(session, "alpha")
            old_id = project.id
        for rid in ("r1", "r2", "r3"):  # hand-built with SQL, not the recorder
            sql_exec(db, INSERT, status="ok", pid=old_id, pname="alpha", rid=rid)
        async with unit_of_work(engine) as session:
            assert await delete_project(session, "alpha") == (0, 3)
        assert sql_all(db, "SELECT DISTINCT project_id, project_name FROM usage_events") == [
            (None, "alpha")
        ]
        async with unit_of_work(engine) as session:
            reborn = await get_or_create_project(session, "alpha")
        # The id may be reused (``projects.id`` is a plain rowid, no AUTOINCREMENT), so what
        # keeps the new project from adopting the old events is that they were detached.
        assert reborn.name == "alpha" and reborn.id is not None
        assert sql_all(db, "SELECT count(*) FROM usage_events WHERE project_id IS NOT NULL") == [
            (0,)
        ]
        assert sql_all(db, "SELECT DISTINCT project_name FROM usage_events") == [("alpha",)]
    finally:
        await engine.dispose()


def test_the_built_wheel_contains_the_migration(tmp_path):
    out = tmp_path / "wheel"
    proc = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    (wheel,) = out.glob("*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    assert "mcp_perplexity_pro/migrations/versions/0002_usage_events.py" in names

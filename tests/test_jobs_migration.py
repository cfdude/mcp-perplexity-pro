"""Task 4.1: the ``research_jobs`` table and migration ``0004`` (agent-research "Job records").
Schema tests end at 0004 through a scratch migrations directory TRUNCATED there, so a later real
revision breaks none of them; the live-database test uses the real migrations on purpose."""

import sqlite3
import subprocess
import zipfile
from pathlib import Path

import pytest
from migration_support import real_chain
from test_chats_migration import truncated

from mcp_perplexity_pro.storage.engine import create_engine_for, database_path
from mcp_perplexity_pro.storage.migrate import (
    backup_path,
    current_revision,
    downgrade,
    head_revision,
    migrate,
)
from mcp_perplexity_pro.storage.models import ResearchJob
from mcp_perplexity_pro.storage.projects import delete_project
from mcp_perplexity_pro.storage.session import unit_of_work

ROOT = Path(__file__).resolve().parent.parent
TS = "2026-10-09 12:00:00.000000"

# column -> NOT NULL?
JOB_COLUMNS = {
    "id": True,
    "project_id": True,
    "query": True,
    "depth": True,
    "response_id": True,
    "status": True,
    "model": False,
    "started_at": True,
    "last_checked_at": False,
    "finished_at": False,
    "cancel_requested_at": False,
    "missing_since": False,
    "result_text": False,
    "sources_json": False,
    "incomplete_reason": False,
    "error_text": False,
    "input_tokens": False,
    "output_tokens": False,
    "total_tokens": False,
    "cost_nano_usd": False,
    "cost_source": False,
    "usage_recorded": True,
}


@pytest.fixture
def upto_0004(tmp_path):
    return truncated(tmp_path, 4, "upto-0004")


@pytest.fixture
def upto_0003(tmp_path):
    return truncated(tmp_path, 3, "upto-0003")


@pytest.fixture
def upto_0002(tmp_path):
    return truncated(tmp_path, 2, "upto-0002")


@pytest.fixture
def settings(make_settings):
    return make_settings()


@pytest.fixture
def db(settings):
    return database_path(settings.data_dir)


def sql_all(db, sql, **params):
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        return conn.execute(sql, params).fetchall()


def sql_exec(db, sql, **params):
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(sql, params)


def names(db):
    return {r[0] for r in sql_all(db, "SELECT name FROM sqlite_master")}


def table_info(db, table):
    # columns: cid, name, type, notnull, dflt_value, pk
    return sql_all(db, f'PRAGMA table_info("{table}")')


_serial = iter(range(1, 10_000))


def add_job(db, project_id, query="q") -> int:
    sql_exec(
        db,
        "INSERT INTO research_jobs (project_id, query, depth, response_id, status, started_at) "
        "VALUES (:p, :q, 'medium', :r, 'queued', :ts)",
        p=project_id,
        q=query,
        r=f"resp_{next(_serial)}",
        ts=TS,
    )
    return sql_all(db, "SELECT max(id) FROM research_jobs")[0][0]


def add_project(db, name) -> int:
    sql_exec(db, "INSERT INTO projects (name) VALUES (:n)", n=name)
    return sql_all(db, "SELECT id FROM projects WHERE name=:n", n=name)[0][0]


def add_event(db, project_id, name, request_id):
    sql_exec(
        db,
        "INSERT INTO usage_events (created_at, tool, api, status, cost_source, project_id, "
        "project_name, request_id) VALUES (:ts, 't', 'agent', 'ok', 'reported', :p, :n, :r)",
        ts=TS,
        p=project_id,
        n=name,
        r=request_id,
    )


def test_a_fresh_database_reaches_0004(settings, db, upto_0004):
    result = migrate(settings, script_location=upto_0004)
    assert result.applied == ("0001", "0002", "0003", "0004")
    assert current_revision(db) == "0004"
    assert "research_jobs" in names(db)


def test_a_0003_database_upgrades_with_rows_unchanged_and_the_0003_backup(
    settings, db, upto_0003, upto_0004
):
    migrate(settings, script_location=upto_0003)
    pid = add_project(db, "alpha")
    add_event(db, pid, "alpha", "r1")
    sql_exec(
        db,
        "INSERT INTO chats (project_id, title, created_at, updated_at) VALUES (:p, 't', :ts, :ts)",
        p=pid,
        ts=TS,
    )
    before = {
        t: sql_all(db, f"SELECT * FROM {t} ORDER BY id")
        for t in ("projects", "usage_events", "chats")
    }

    result = migrate(settings, script_location=upto_0004)
    assert result.applied == ("0004",)
    assert result.backup == backup_path(settings.data_dir, "0003")
    assert result.backup.exists()
    assert "research_jobs" not in names(result.backup)  # the backup is the 0003 database
    for table, rows in before.items():
        assert sql_all(db, f"SELECT * FROM {table} ORDER BY id") == rows


def test_a_live_0002_database_goes_straight_to_head_with_one_backup(settings, db, upto_0002):
    migrate(settings, script_location=upto_0002)
    pid = add_project(db, "live")
    add_event(db, pid, "live", "r1")
    before = sql_all(db, "SELECT * FROM usage_events ORDER BY id")

    result = migrate(settings)  # the REAL migrations
    chain = real_chain()
    assert chain[2:4] == ["0003", "0004"]
    assert result.applied == tuple(chain[2:])
    assert current_revision(db) == head_revision()
    assert sql_all(db, "SELECT * FROM usage_events ORDER BY id") == before
    backups = sorted(p.name for p in settings.data_dir.glob("*backup*"))
    assert backups == [backup_path(settings.data_dir, "0002").name]
    assert not backup_path(settings.data_dir, "0003").exists()


def test_up_down_up_leaves_projects_chats_and_usage_events_untouched(settings, db, upto_0004):
    migrate(settings, script_location=upto_0004)
    pid = add_project(db, "kept")
    add_event(db, pid, "kept", "r1")
    sql_exec(
        db,
        "INSERT INTO chats (project_id, title, created_at, updated_at) VALUES (:p, 't', :ts, :ts)",
        p=pid,
        ts=TS,
    )
    add_job(db, pid)
    kept = {
        t: sql_all(db, f"SELECT * FROM {t} ORDER BY id")
        for t in ("projects", "usage_events", "chats")
    }

    result = downgrade(settings, "0003", script_location=upto_0004)
    assert result.applied == ("0004",)
    assert current_revision(db) == "0003"
    assert not {n for n in names(db) if "research_jobs" in n}  # the indexes went with the table
    for table, rows in kept.items():
        assert sql_all(db, f"SELECT * FROM {table} ORDER BY id") == rows

    again = migrate(settings, script_location=upto_0004)
    assert again.applied == ("0004",)
    assert sql_all(db, "SELECT count(*) FROM research_jobs") == [(0,)]
    for table, rows in kept.items():
        assert sql_all(db, f"SELECT * FROM {table} ORDER BY id") == rows


def test_every_column_key_index_and_the_unique_response_id_are_as_designed(settings, db, upto_0004):
    migrate(settings, script_location=upto_0004)
    assert {r[1]: bool(r[3]) for r in table_info(db, "research_jobs")} == JOB_COLUMNS
    assert [r[1] for r in table_info(db, "research_jobs") if r[5]] == ["id"]
    defaults = {r[1]: r[4] for r in table_info(db, "research_jobs")}
    assert defaults["usage_recorded"] == "0"
    # columns: id, seq, table, from, to, on_update, on_delete, match
    keys = sql_all(db, 'PRAGMA foreign_key_list("research_jobs")')
    assert [(k[2], k[3], k[4], k[6]) for k in keys] == [("projects", "project_id", "id", "CASCADE")]
    indexes = {
        name: [r[2] for r in sql_all(db, f'PRAGMA index_info("{name}")')]
        for (name,) in sql_all(
            db,
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_research_jobs%'",
        )
    }
    assert indexes == {
        "ix_research_jobs_project_id_id": ["project_id", "id"],
        "ix_research_jobs_status": ["status"],
    }
    ddl = sql_all(db, "SELECT sql FROM sqlite_master WHERE name='research_jobs'")[0][0]
    assert "AUTOINCREMENT" in ddl
    pid = add_project(db, "p")
    first = add_job(db, pid)
    with pytest.raises(sqlite3.IntegrityError):  # response_id is unique
        sql_exec(
            db,
            "INSERT INTO research_jobs (project_id, query, depth, response_id, status, started_at)"
            " SELECT project_id, query, depth, response_id, status, started_at FROM research_jobs"
            " WHERE id = :i",
            i=first,
        )


def test_the_orm_model_matches_the_migrated_table(settings, db, upto_0004):
    migrate(settings, script_location=upto_0004)
    migrated = {r[1]: bool(r[3]) for r in table_info(db, "research_jobs")}
    assert {c.name: not c.nullable for c in ResearchJob.__table__.columns} == migrated
    assert ResearchJob.__tablename__ == "research_jobs"
    assert {i.name for i in ResearchJob.__table__.indexes} == {
        n for n in names(db) if n.startswith("ix_research_jobs_")
    }
    (key,) = ResearchJob.__table__.c.project_id.foreign_keys
    assert key.ondelete == "CASCADE"
    assert ResearchJob.__table__.dialect_options["sqlite"]["autoincrement"] is True
    assert {c.name for c in ResearchJob.__table__.constraints if c.name} == {
        "uq_research_jobs_response_id"
    }


def test_a_deleted_newest_job_id_is_not_reused(settings, db, upto_0004):
    migrate(settings, script_location=upto_0004)
    pid = add_project(db, "p")
    first, second = add_job(db, pid), add_job(db, pid)
    assert sql_all(db, "SELECT seq FROM sqlite_sequence WHERE name='research_jobs'") == [(second,)]
    sql_exec(db, "DELETE FROM research_jobs WHERE id=:i", i=second)
    third = add_job(db, pid)
    assert third not in (first, second) and third > second


async def test_a_project_deleted_with_two_jobs_removes_and_counts_them(settings, db, upto_0004):
    migrate(settings, script_location=upto_0004)
    doomed, safe = add_project(db, "doomed"), add_project(db, "safe")
    add_job(db, doomed)
    add_job(db, doomed)
    keep = add_job(db, safe)
    add_event(db, doomed, "doomed", "r-doomed")
    engine = create_engine_for(settings)
    try:
        async with unit_of_work(engine) as session:
            outcome = await delete_project(session, "doomed")
    finally:
        await engine.dispose()
    assert outcome == (2, 1)  # two jobs removed; the usage event is detached, not removed
    assert sql_all(db, "SELECT id FROM research_jobs") == [(keep,)]
    # the event survives, still carrying the project's name, so it stays reportable by name
    assert sql_all(db, "SELECT project_id, project_name FROM usage_events") == [(None, "doomed")]


@pytest.mark.build
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
    assert (
        "mcp_perplexity_pro/migrations/versions/0004_research_jobs.py"
        in zipfile.ZipFile(wheel).namelist()
    )

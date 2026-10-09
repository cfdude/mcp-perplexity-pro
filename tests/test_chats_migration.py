"""Task 3.1: the ``chats`` and ``chat_messages`` tables and migration ``0003`` (agent-chat
"Chat storage"). Every test that needs the schema ends at 0003 through a scratch migrations
directory TRUNCATED there, so adding a later real revision breaks none of them."""

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
    migrate,
)
from mcp_perplexity_pro.storage.models import Chat, ChatMessage
from mcp_perplexity_pro.storage.projects import delete_project
from mcp_perplexity_pro.storage.session import unit_of_work

ROOT = Path(__file__).resolve().parent.parent

# column -> NOT NULL?
CHAT_COLUMNS = {
    "id": True,
    "project_id": True,
    "title": True,
    "created_at": True,
    "updated_at": True,
}
MESSAGE_COLUMNS = {
    "id": True,
    "chat_id": True,
    "role": True,
    "content": True,
    "created_at": True,
    "response_id": False,
    "model": False,
    "preset": False,
    "sources_json": False,
}
TS = "2026-10-09 12:00:00.000000"


def truncated(tmp_path, last: int, name: str) -> Path:
    """A scratch copy of the real migrations keeping only revisions up to ``last``."""
    target = tmp_path / name
    shutil.copytree(MIGRATIONS_DIR, target, ignore=shutil.ignore_patterns("__pycache__"))
    for path in (target / "versions").glob("*.py"):
        if int(path.name[:4]) > last:
            path.unlink()
    return target


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


def add_chat(db, project_id, title="t") -> int:
    sql_exec(
        db,
        "INSERT INTO chats (project_id, title, created_at, updated_at) VALUES (:p, :t, :ts, :ts)",
        p=project_id,
        t=title,
        ts=TS,
    )
    return sql_all(db, "SELECT max(id) FROM chats")[0][0]


def add_message(db, chat_id, role="user", content="hi"):
    sql_exec(
        db,
        "INSERT INTO chat_messages (chat_id, role, content, created_at) VALUES (:c, :r, :x, :ts)",
        c=chat_id,
        r=role,
        x=content,
        ts=TS,
    )


def test_a_fresh_database_reaches_0003(settings, db, upto_0003):
    result = migrate(settings, script_location=upto_0003)
    assert result.applied == ("0001", "0002", "0003")
    assert current_revision(db) == "0003"
    assert {"chats", "chat_messages"} <= names(db)


def test_a_0002_database_with_rows_upgrades_unchanged_and_backed_up(
    settings, db, upto_0002, upto_0003
):
    migrate(settings, script_location=upto_0002)
    sql_exec(db, "INSERT INTO projects (name) VALUES ('alpha')")
    pid = sql_all(db, "SELECT id FROM projects")[0][0]
    for rid in ("r1", "r2"):
        sql_exec(
            db,
            "INSERT INTO usage_events (created_at, tool, api, status, cost_source, project_id, "
            "project_name, request_id) VALUES (:ts, 't', 'agent', 'ok', 'reported', :p, "
            "'alpha', :r)",
            ts=TS,
            p=pid,
            r=rid,
        )
    projects = sql_all(db, "SELECT * FROM projects ORDER BY id")
    events = sql_all(db, "SELECT * FROM usage_events ORDER BY id")

    result = migrate(settings, script_location=upto_0003)
    assert result.applied == ("0003",)
    assert sql_all(db, "SELECT * FROM projects ORDER BY id") == projects
    assert sql_all(db, "SELECT * FROM usage_events ORDER BY id") == events
    assert result.backup == backup_path(settings.data_dir, "0002")
    assert result.backup.exists()
    assert "chats" not in names(result.backup)  # the backup is the 0002 database


def test_up_down_up_leaves_projects_and_usage_events_untouched(settings, db, upto_0003):
    migrate(settings, script_location=upto_0003)
    sql_exec(db, "INSERT INTO projects (name) VALUES ('kept')")
    pid = sql_all(db, "SELECT id FROM projects")[0][0]
    sql_exec(
        db,
        "INSERT INTO usage_events (created_at, tool, api, status, cost_source, project_id, "
        "project_name) VALUES (:ts, 't', 'agent', 'ok', 'reported', :p, 'kept')",
        ts=TS,
        p=pid,
    )
    add_message(db, add_chat(db, pid))
    projects = sql_all(db, "SELECT * FROM projects")
    events = sql_all(db, "SELECT * FROM usage_events")

    result = downgrade(settings, "0002", script_location=upto_0003)
    assert result.applied == ("0003",)
    assert current_revision(db) == "0002"
    assert not {"chats", "chat_messages"} & names(db)
    assert not {n for n in names(db) if "chat" in n}  # the indexes went with the tables
    assert sql_all(db, "SELECT * FROM projects") == projects
    assert sql_all(db, "SELECT * FROM usage_events") == events

    again = migrate(settings, script_location=upto_0003)
    assert again.applied == ("0003",)
    assert sql_all(db, "SELECT count(*) FROM chats") == [(0,)]
    assert sql_all(db, "SELECT * FROM projects") == projects


def table_info(db, table):
    # columns: cid, name, type, notnull, dflt_value, pk
    return sql_all(db, f'PRAGMA table_info("{table}")')


def test_every_column_and_foreign_key_rule_is_as_designed(settings, db, upto_0003):
    migrate(settings, script_location=upto_0003)
    assert {r[1]: bool(r[3]) for r in table_info(db, "chats")} == CHAT_COLUMNS
    assert {r[1]: bool(r[3]) for r in table_info(db, "chat_messages")} == MESSAGE_COLUMNS
    assert [r[1] for r in table_info(db, "chats") if r[5]] == ["id"]
    assert [r[1] for r in table_info(db, "chat_messages") if r[5]] == ["id"]
    # columns: id, seq, table, from, to, on_update, on_delete, match
    chat_keys = sql_all(db, 'PRAGMA foreign_key_list("chats")')
    assert [(k[2], k[3], k[4], k[6]) for k in chat_keys] == [
        ("projects", "project_id", "id", "CASCADE")
    ]
    message_keys = sql_all(db, 'PRAGMA foreign_key_list("chat_messages")')
    assert [(k[2], k[3], k[4], k[6]) for k in message_keys] == [
        ("chats", "chat_id", "id", "CASCADE")
    ]
    indexes = {
        name: [r[2] for r in sql_all(db, f'PRAGMA index_info("{name}")')]
        for (name,) in sql_all(
            db, "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_chat%'"
        )
    }
    assert indexes == {
        "ix_chats_project_id_updated_at": ["project_id", "updated_at"],
        "ix_chat_messages_chat_id_id": ["chat_id", "id"],
    }
    assert "AUTOINCREMENT" in sql_all(db, "SELECT sql FROM sqlite_master WHERE name='chats'")[0][0]


def test_the_orm_models_match_the_migrated_tables(settings, db, upto_0003):
    migrate(settings, script_location=upto_0003)
    for model, table in ((Chat, "chats"), (ChatMessage, "chat_messages")):
        migrated = {r[1]: bool(r[3]) for r in table_info(db, table)}
        assert {c.name: not c.nullable for c in model.__table__.columns} == migrated
        assert model.__tablename__ == table
        assert {i.name for i in model.__table__.indexes} == {
            n for n in names(db) if n.startswith(f"ix_{table}_")
        }
        for column in model.__table__.columns:
            for key in column.foreign_keys:
                assert key.ondelete == "CASCADE"
    assert Chat.__table__.dialect_options["sqlite"]["autoincrement"] is True


def test_sqlite_sequence_holds_chats_and_a_deleted_newest_id_is_not_reused(settings, db, upto_0003):
    migrate(settings, script_location=upto_0003)
    sql_exec(db, "INSERT INTO projects (name) VALUES ('p')")
    pid = sql_all(db, "SELECT id FROM projects")[0][0]
    first, second = add_chat(db, pid), add_chat(db, pid)
    assert sql_all(db, "SELECT seq FROM sqlite_sequence WHERE name='chats'") == [(second,)]
    sql_exec(db, "DELETE FROM chats WHERE id=:i", i=second)
    third = add_chat(db, pid)
    assert third not in (first, second) and third > second


async def test_a_project_deleted_with_two_chats_and_six_messages_removes_them_all(
    settings, db, upto_0003
):
    migrate(settings, script_location=upto_0003)
    sql_exec(db, "INSERT INTO projects (name) VALUES ('doomed')")
    sql_exec(db, "INSERT INTO projects (name) VALUES ('safe')")
    doomed, safe = (
        sql_all(db, "SELECT id FROM projects WHERE name=:n", n=n)[0][0] for n in ("doomed", "safe")
    )
    for _ in range(2):
        chat = add_chat(db, doomed)
        for _ in range(3):
            add_message(db, chat)
    keep = add_chat(db, safe)
    add_message(db, keep)
    engine = create_engine_for(settings)
    try:
        async with unit_of_work(engine) as session:
            outcome = await delete_project(session, "doomed")
    finally:
        await engine.dispose()
    assert outcome == (2, 0)  # the chats are counted; their messages (two hops) are not
    assert sql_all(db, "SELECT count(*) FROM chats WHERE project_id=:p", p=doomed) == [(0,)]
    assert sql_all(db, "SELECT count(*) FROM chat_messages") == [(1,)]  # only the safe chat's
    assert sql_all(db, "SELECT count(*) FROM chats") == [(1,)]


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
        "mcp_perplexity_pro/migrations/versions/0003_chats.py" in zipfile.ZipFile(wheel).namelist()
    )

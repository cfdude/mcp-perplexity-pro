"""routing-v2 task 5.2: migration ``0006`` (``chat_messages.tier`` and ``routed_model``).

Schema tests end at 0006 through a scratch migrations directory truncated there, so a later real
revision breaks none of them. The downgrade must be ``ALTER TABLE ... DROP COLUMN``: batch mode
would rebuild ``chat_messages`` and cascade-delete every ``embedding_chunks`` row of a chat.
"""

import sqlite3

import pytest
from test_chats_migration import MESSAGE_COLUMNS, table_info, truncated
from test_embeddings_migration import add_chat, add_chunk, add_job, chunk_count

from mcp_perplexity_pro.storage.engine import database_path
from mcp_perplexity_pro.storage.migrate import (
    backup_path,
    current_revision,
    downgrade,
    head_revision,
    migrate,
)

NEW_COLUMNS = {"tier": False, "routed_model": False}


@pytest.fixture
def upto_0006(tmp_path):
    return truncated(tmp_path, 6, "upto-0006")


@pytest.fixture
def upto_0005(tmp_path):
    return truncated(tmp_path, 5, "upto-0005")


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


def add_project(db, name):
    sql_exec(db, "INSERT INTO projects (name) VALUES (:n)", n=name)
    return sql_all(db, "SELECT id FROM projects WHERE name=:n", n=name)[0][0]


def columns(db):
    return {r[1]: bool(r[3]) for r in table_info(db, "chat_messages")}


def test_a_fresh_database_reaches_0006_and_the_columns_are_nullable(settings, db, upto_0006):
    result = migrate(settings, script_location=upto_0006)
    assert result.applied == ("0001", "0002", "0003", "0004", "0005", "0006")
    assert current_revision(db) == "0006"
    assert columns(db) == {**MESSAGE_COLUMNS, **NEW_COLUMNS}


def test_the_real_head_is_at_least_0006():
    assert int(head_revision()) >= 6


def test_a_0005_database_upgrades_with_rows_unchanged_and_the_0005_backup(
    settings, db, upto_0005, upto_0006
):
    migrate(settings, script_location=upto_0005)
    pid = add_project(db, "alpha")
    _, messages = add_chat(db, pid, 3)
    add_chunk(db, pid, "chat", message=messages[0])
    before = {
        t: sql_all(db, f"SELECT * FROM {t} ORDER BY id")
        for t in ("projects", "chats", "chat_messages", "embedding_chunks")
    }
    result = migrate(settings, script_location=upto_0006)
    assert result.applied == ("0006",)
    assert result.backup == backup_path(settings.data_dir, "0005") and result.backup.exists()
    assert "tier" not in {r[1] for r in table_info(result.backup, "chat_messages")}
    for table in ("projects", "chats", "embedding_chunks"):
        assert sql_all(db, f"SELECT * FROM {table} ORDER BY id") == before[table]
    # the old rows gain the two columns as NULL and keep every earlier value
    after = sql_all(db, "SELECT * FROM chat_messages ORDER BY id")
    assert [row[:-2] for row in after] == before["chat_messages"]
    assert all(row[-2:] == (None, None) for row in after)


def test_a_downgrade_keeps_chat_rows_and_every_vector_and_drops_the_two_columns(
    settings, db, upto_0006
):
    migrate(settings, script_location=upto_0006)
    pid = add_project(db, "kept")
    _, messages = add_chat(db, pid, 2)
    job = add_job(db, pid)
    add_chunk(db, pid, "chat", message=messages[0])
    add_chunk(db, pid, "chat", message=messages[1])
    add_chunk(db, pid, "job", job=job)
    add_chunk(db, pid, "text", key="k")
    sql_exec(
        db,
        "UPDATE chat_messages SET tier = 'standard', routed_model = 'x/m' WHERE id = :i",
        i=messages[0],
    )
    base_columns = list(MESSAGE_COLUMNS)
    kept_messages = sql_all(db, f"SELECT {', '.join(base_columns)} FROM chat_messages ORDER BY id")
    kept_chunks = sql_all(db, "SELECT * FROM embedding_chunks ORDER BY id")
    assert chunk_count(db) == 4

    result = downgrade(settings, "0005", script_location=upto_0006)
    assert result.applied == ("0006",) and current_revision(db) == "0005"
    assert columns(db) == MESSAGE_COLUMNS  # the two columns are gone
    assert sql_all(db, f"SELECT {', '.join(base_columns)} FROM chat_messages ORDER BY id") == (
        kept_messages
    )
    # every vector survives, the chat chunks included: no table rebuild cascaded into them
    assert chunk_count(db) == 4
    assert sql_all(db, "SELECT * FROM embedding_chunks ORDER BY id") == kept_chunks


def test_up_down_up_gives_back_two_empty_columns(settings, db, upto_0006):
    migrate(settings, script_location=upto_0006)
    pid = add_project(db, "p")
    _, messages = add_chat(db, pid)
    sql_exec(db, "UPDATE chat_messages SET tier = 'light' WHERE id = :i", i=messages[0])
    downgrade(settings, "0005", script_location=upto_0006)
    again = migrate(settings, script_location=upto_0006)
    assert again.applied == ("0006",)
    assert sql_all(db, "SELECT tier, routed_model FROM chat_messages") == [(None, None)]


def test_the_sqlite_in_use_supports_drop_column():
    # ALTER TABLE ... DROP COLUMN needs 3.35.0 (2021-03-12); the project already needs it for
    # ``... RETURNING id`` in storage/embeddings.py (measured 3.53.1 on 2026-11-11)
    assert sqlite3.sqlite_version_info >= (3, 35, 0)


def test_the_downgrade_is_drop_column_and_never_batch_mode():
    from importlib import import_module

    source = import_module(
        "mcp_perplexity_pro.migrations.versions.0006_chat_message_route"
    ).downgrade.__code__.co_names
    assert "execute" in source and "batch_alter_table" not in source

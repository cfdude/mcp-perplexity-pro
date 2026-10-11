"""Task 3.2 (py-embeddings): the ``embedding_chunks`` table and migration ``0005`` (embeddings-store
spec). Schema tests end at 0005 through a scratch migrations directory truncated there."""

import sqlite3

import pytest
from test_chats_migration import truncated

from mcp_perplexity_pro.storage.engine import create_engine_for, database_path
from mcp_perplexity_pro.storage.migrate import (
    backup_path,
    current_revision,
    downgrade,
    migrate,
)
from mcp_perplexity_pro.storage.models import EmbeddingChunk
from mcp_perplexity_pro.storage.projects import delete_project
from mcp_perplexity_pro.storage.session import unit_of_work

TS = "2026-10-11 12:00:00.000000"
COLUMNS = {
    "id": True,
    "project_id": True,
    "source": True,
    "chat_message_id": False,
    "research_job_id": False,
    "ref": True,
    "chunk_index": True,
    "text": True,
    "text_hash": True,
    "model": True,
    "dimensions": True,
    "encoding": True,
    "vector": True,
    "created_at": True,
}
INDEXES = {
    "ix_embedding_chunks_project_triple",
    "ix_embedding_chunks_project_source",
    "ix_embedding_chunks_chat_message_id",
    "ix_embedding_chunks_research_job_id",
}


@pytest.fixture
def upto_0005(tmp_path):
    return truncated(tmp_path, 5, "upto-0005")


@pytest.fixture
def upto_0004(tmp_path):
    return truncated(tmp_path, 4, "upto-0004")


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


def add_project(db, name):
    sql_exec(db, "INSERT INTO projects (name) VALUES (:n)", n=name)
    return sql_all(db, "SELECT id FROM projects WHERE name=:n", n=name)[0][0]


def add_chat(db, pid, messages=1):
    sql_exec(
        db,
        "INSERT INTO chats (project_id, title, created_at, updated_at) VALUES (:p, 't', :ts, :ts)",
        p=pid,
        ts=TS,
    )
    chat = sql_all(db, "SELECT max(id) FROM chats")[0][0]
    ids = []
    for i in range(messages):
        sql_exec(
            db,
            "INSERT INTO chat_messages (chat_id, role, content, created_at) "
            "VALUES (:c, 'user', :t, :ts)",
            c=chat,
            t=f"message {i}",
            ts=TS,
        )
        ids.append(sql_all(db, "SELECT max(id) FROM chat_messages")[0][0])
    return chat, ids


_serial = iter(range(1, 100_000))


def add_job(db, pid):
    sql_exec(
        db,
        "INSERT INTO research_jobs (project_id, query, depth, response_id, status, started_at) "
        "VALUES (:p, 'q', 'medium', :r, 'completed', :ts)",
        p=pid,
        r=f"resp_{next(_serial)}",
        ts=TS,
    )
    return sql_all(db, "SELECT max(id) FROM research_jobs")[0][0]


def add_chunk(db, pid, source, *, message=None, job=None, key=None, index=0, model="m"):
    ref = {"chat": f"c:{message}", "job": f"j:{job}", "text": f"t:{key}"}[source]
    sql_exec(
        db,
        "INSERT INTO embedding_chunks (project_id, source, chat_message_id, research_job_id, ref,"
        " chunk_index, text, text_hash, model, dimensions, encoding, vector, created_at) VALUES "
        "(:p, :s, :m, :j, :r, :i, 'x', 'h', :model, 8, 'int8', :v, :ts)",
        p=pid,
        s=source,
        m=message,
        j=job,
        r=ref,
        i=index,
        model=model,
        v=b"\x01" * 8,
        ts=TS,
    )


def chunk_count(db):
    return sql_all(db, "SELECT count(*) FROM embedding_chunks")[0][0]


def test_a_fresh_database_reaches_0005(settings, db, upto_0005):
    result = migrate(settings, script_location=upto_0005)
    assert result.applied == ("0001", "0002", "0003", "0004", "0005")
    assert current_revision(db) == "0005" and "embedding_chunks" in names(db)


def test_a_0004_database_upgrades_with_rows_unchanged_and_the_0004_backup(
    settings, db, upto_0004, upto_0005
):
    migrate(settings, script_location=upto_0004)
    pid = add_project(db, "alpha")
    add_chat(db, pid, 2)
    add_job(db, pid)
    before = {
        t: sql_all(db, f"SELECT * FROM {t} ORDER BY id")
        for t in ("projects", "chats", "chat_messages", "research_jobs")
    }
    result = migrate(settings, script_location=upto_0005)
    assert result.applied == ("0005",)
    assert result.backup == backup_path(settings.data_dir, "0004") and result.backup.exists()
    assert "embedding_chunks" not in names(result.backup)
    for table, rows in before.items():
        assert sql_all(db, f"SELECT * FROM {table} ORDER BY id") == rows


def test_downgrade_drops_only_the_table_and_its_indexes_and_upgrade_recreates_it(
    settings, db, upto_0005
):
    migrate(settings, script_location=upto_0005)
    pid = add_project(db, "kept")
    chat, (message,) = add_chat(db, pid)
    add_chunk(db, pid, "chat", message=message)
    kept = {t: sql_all(db, f"SELECT * FROM {t} ORDER BY id") for t in ("projects", "chats")}
    result = downgrade(settings, "0004", script_location=upto_0005)
    assert result.applied == ("0005",) and current_revision(db) == "0004"
    assert not {n for n in names(db) if "embedding_chunks" in n}
    for table, rows in kept.items():
        assert sql_all(db, f"SELECT * FROM {table} ORDER BY id") == rows
    migrate(settings, script_location=upto_0005)
    assert chunk_count(db) == 0


def test_the_orm_model_matches_the_migrated_table(settings, db, upto_0005):
    migrate(settings, script_location=upto_0005)
    info = sql_all(db, 'PRAGMA table_info("embedding_chunks")')
    assert {r[1]: bool(r[3]) for r in info} == COLUMNS
    assert {c.name: not c.nullable for c in EmbeddingChunk.__table__.columns} == COLUMNS
    migrated = {n for n in names(db) if n.startswith("ix_embedding_chunks_")}
    assert {i.name for i in EmbeddingChunk.__table__.indexes} == migrated == INDEXES
    keys = {(k[3], k[2], k[6]) for k in sql_all(db, 'PRAGMA foreign_key_list("embedding_chunks")')}
    assert keys == {
        ("project_id", "projects", "CASCADE"),
        ("chat_message_id", "chat_messages", "CASCADE"),
        ("research_job_id", "research_jobs", "CASCADE"),
    }
    orm_keys = {
        (c.name, next(iter(c.foreign_keys)).column.table.name, next(iter(c.foreign_keys)).ondelete)
        for c in EmbeddingChunk.__table__.columns
        if c.foreign_keys
    }
    assert orm_keys == keys
    assert {c.name for c in EmbeddingChunk.__table__.constraints if c.name} == {
        "ck_embedding_chunks_source_keys",
        "uq_embedding_chunks_item",
    }
    ddl = sql_all(db, "SELECT sql FROM sqlite_master WHERE name='embedding_chunks'")[0][0]
    assert "AUTOINCREMENT" in ddl and "ck_embedding_chunks_source_keys" in ddl
    assert "uq_embedding_chunks_item" in ddl
    assert EmbeddingChunk.__table__.dialect_options["sqlite"]["autoincrement"] is True
    partial = {
        n: s
        for n, s in sql_all(
            db, "SELECT name, sql FROM sqlite_master WHERE name LIKE 'ix_embedding_chunks_%_id'"
        )
    }
    assert all("IS NOT NULL" in sql for sql in partial.values()) and len(partial) == 2


def test_the_check_constraint_refuses_a_source_and_keys_that_disagree(settings, db, upto_0005):
    migrate(settings, script_location=upto_0005)
    pid = add_project(db, "p")
    _, (message,) = add_chat(db, pid)
    job = add_job(db, pid)
    with pytest.raises(sqlite3.IntegrityError):  # chat without a message
        add_chunk(db, pid, "chat", message=None)
    with pytest.raises(sqlite3.IntegrityError):  # text with a job
        add_chunk(db, pid, "text", job=job, key="k")
    with pytest.raises(sqlite3.IntegrityError):  # job with a message
        add_chunk(db, pid, "job", job=job, message=message)
    add_chunk(db, pid, "chat", message=message)
    add_chunk(db, pid, "job", job=job)
    add_chunk(db, pid, "text", key="k")
    assert chunk_count(db) == 3


def test_a_plain_duplicate_is_refused_and_a_conflict_ignoring_insert_stores_one_row(
    settings, db, upto_0005
):
    migrate(settings, script_location=upto_0005)
    pid = add_project(db, "p")
    add_chunk(db, pid, "text", key="k")
    with pytest.raises(sqlite3.IntegrityError):
        add_chunk(db, pid, "text", key="k")
    sql_exec(
        db,
        "INSERT INTO embedding_chunks (project_id, source, ref, chunk_index, text, text_hash,"
        " model, dimensions, encoding, vector, created_at) VALUES (:p, 'text', 't:k', 0, 'y', 'h2',"
        " 'm', 8, 'int8', :v, :ts) ON CONFLICT DO NOTHING",
        p=pid,
        v=b"\x02" * 8,
        ts=TS,
    )
    assert chunk_count(db) == 1
    add_chunk(db, pid, "text", key="k", model="other")  # another model is another row
    assert chunk_count(db) == 2


def test_deleting_a_chat_a_job_and_a_project_removes_their_chunks_only(settings, db, upto_0005):
    migrate(settings, script_location=upto_0005)
    pid, other = add_project(db, "p"), add_project(db, "other")
    chat, (m1, m2) = add_chat(db, pid, 2)
    job = add_job(db, pid)
    add_chunk(db, pid, "chat", message=m1)
    add_chunk(db, pid, "chat", message=m2)
    add_chunk(db, pid, "job", job=job)
    add_chunk(db, pid, "text", key="k")
    other_chat, (om,) = add_chat(db, other)
    add_chunk(db, other, "chat", message=om)
    sql_exec(db, "DELETE FROM chats WHERE id=:c", c=chat)  # cascades messages then chunks
    assert chunk_count(db) == 3  # job, text and the other project's chat chunk remain
    sql_exec(db, "DELETE FROM research_jobs WHERE id=:j", j=job)
    assert chunk_count(db) == 2
    sql_exec(db, "DELETE FROM projects WHERE id=:p", p=pid)
    assert sql_all(db, "SELECT project_id FROM embedding_chunks") == [(other,)]


def test_a_reused_message_id_has_no_chunk_of_the_old_message(settings, db, upto_0005):
    migrate(settings, script_location=upto_0005)
    pid = add_project(db, "p")
    chat, (first, second) = add_chat(db, pid, 2)
    add_chunk(db, pid, "chat", message=second)
    sql_exec(db, "DELETE FROM chat_messages WHERE id=:i", i=second)
    sql_exec(
        db,
        "INSERT INTO chat_messages (chat_id, role, content, created_at) "
        "VALUES (:c, 'user', 'new', :ts)",
        c=chat,
        ts=TS,
    )
    reused = sql_all(db, "SELECT max(id) FROM chat_messages")[0][0]
    assert reused == second  # chat_messages has no AUTOINCREMENT, so the id comes back
    assert chunk_count(db) == 0  # the cascade removed the old message's chunk with it


async def test_project_delete_counts_job_and_text_chunks_but_not_the_cascaded_chat_chunks(
    settings, db, upto_0005
):
    migrate(settings, script_location=upto_0005)

    async def delete(name):
        engine = create_engine_for(settings)
        try:
            async with unit_of_work(engine) as session:
                return await delete_project(session, name)
        finally:
            await engine.dispose()

    plain, loaded = add_project(db, "plain"), add_project(db, "loaded")
    for pid in (plain, loaded):
        _, (message,) = add_chat(db, pid)
        job = add_job(db, pid)
        if pid == loaded:
            add_chunk(db, pid, "chat", message=message)
            add_chunk(db, pid, "job", job=job)
            add_chunk(db, pid, "text", key="k")
    baseline = await delete("plain")
    outcome = await delete("loaded")
    # `chats` is deleted first (name order) and cascades its chunk uncounted; the job and text
    # chunks are still there when `embedding_chunks` is deleted, so they are counted
    assert outcome[0] == baseline[0] + 2 and outcome[1] == baseline[1]
    assert chunk_count(db) == 0


def test_the_cascade_deletes_use_the_partial_indexes(settings, db, upto_0005):
    migrate(settings, script_location=upto_0005)
    for column, index in (
        ("chat_message_id", "ix_embedding_chunks_chat_message_id"),
        ("research_job_id", "ix_embedding_chunks_research_job_id"),
    ):
        plan = sql_all(db, f"EXPLAIN QUERY PLAN DELETE FROM embedding_chunks WHERE {column} = 5")
        assert any(index in str(row) for row in plan), plan

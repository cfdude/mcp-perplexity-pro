"""Task 1.1/1.2: how project deletion finds and treats tables that reference ``projects``.

Test-only tables declare the foreign key three ways (``ON DELETE CASCADE``, ``ON DELETE SET
NULL``, no action). They pin what ``delete_project`` does with each, and what SQLite itself
reports about each key, because the retained-table convention (local-storage "Retained
records") depends on reading the delete rule from ``PRAGMA foreign_key_list`` instead of
SQLAlchemy's inspector.
"""

import pytest
from sqlalchemy import inspect, text

from mcp_perplexity_pro.storage.projects import (
    _scoped_tables,
    delete_project,
    get_or_create_project,
)
from mcp_perplexity_pro.storage.session import unit_of_work

TABLES = {
    "t_cascade": "project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE",
    "t_setnull": "project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL",
    "t_noaction": "project_id INTEGER NOT NULL REFERENCES projects(id)",
}


@pytest.fixture
async def engine(storage_engine):
    async with storage_engine.begin() as conn:
        for name, column in TABLES.items():
            await conn.execute(text(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, {column})"))
        await conn.execute(
            text(
                "CREATE TABLE t_two_hop (id INTEGER PRIMARY KEY, "
                "parent INTEGER NOT NULL REFERENCES t_cascade(id) ON DELETE CASCADE)"
            )
        )
    return storage_engine


async def seed(engine, name="alpha"):
    async with unit_of_work(engine) as session:
        project = await get_or_create_project(session, name)
        for table, count in (("t_cascade", 2), ("t_setnull", 3), ("t_noaction", 1)):
            for _ in range(count):
                await session.execute(
                    text(f"INSERT INTO {table} (project_id) VALUES (:p)"), {"p": project.id}
                )
        parent = (await session.execute(text("SELECT min(id) FROM t_cascade"))).scalar_one()
        await session.execute(text("INSERT INTO t_two_hop (parent) VALUES (:p)"), {"p": parent})
        return project.id


async def count(engine, table):
    async with engine.connect() as conn:
        return (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def test_all_three_tables_are_found_as_scoped(engine):
    async with engine.connect() as conn:
        found = await conn.run_sync(_scoped_tables)
    assert {(table, column) for table, column in found} >= {
        ("t_cascade", "project_id"),
        ("t_setnull", "project_id"),
        ("t_noaction", "project_id"),
    }
    assert "t_two_hop" not in {table for table, _ in found}  # points at t_cascade, not projects


async def test_foundation_behavior_deletes_and_counts_every_directly_referencing_table(engine):
    await seed(engine)
    async with unit_of_work(engine) as session:
        removed = await delete_project(session, "alpha")
    assert removed == 2 + 3 + 1  # the two-hop row went by cascade and is not counted
    for table in (*TABLES, "t_two_hop"):
        assert await count(engine, table) == 0


async def test_inspector_hides_the_delete_rule_but_pragma_reports_it(engine):
    async with engine.connect() as conn:

        def read(sync_conn):
            insp = inspect(sync_conn)
            options = {t: insp.get_foreign_keys(t)[0]["options"] for t in TABLES}
            rules = {
                t: sync_conn.exec_driver_sql(f'PRAGMA foreign_key_list("{t}")').fetchone()
                for t in TABLES
            }
            return options, rules

        options, rules = await conn.run_sync(read)
    assert options == {"t_cascade": {}, "t_setnull": {}, "t_noaction": {}}
    # PRAGMA columns: id, seq, table, from, to, on_update, on_delete, match
    assert {t: row[6] for t, row in rules.items()} == {
        "t_cascade": "CASCADE",
        "t_setnull": "SET NULL",
        "t_noaction": "NO ACTION",
    }

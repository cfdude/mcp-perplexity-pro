"""Task 1.1/1.2: how project deletion finds and treats tables that reference ``projects``.

Test-only tables declare the foreign key three ways (``ON DELETE CASCADE``, ``ON DELETE SET
NULL``, no action). They pin what ``delete_project`` does with each, and what SQLite itself
reports about each key, because the retained-table convention (local-storage "Retained
records") depends on reading the delete rule from ``PRAGMA foreign_key_list`` instead of
SQLAlchemy's inspector.
"""

import pytest
from sqlalchemy import inspect, text

from mcp_perplexity_pro.storage.engine import StorageError
from mcp_perplexity_pro.storage.projects import (
    _scoped_tables,
    delete_project,
    get_or_create_project,
)
from mcp_perplexity_pro.storage.session import unit_of_work

# tables that exist for other reasons (the conftest fixture, the real migrations)
KNOWN = {"notes", "usage_events"}

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
    assert {(t.table, t.column, t.retained) for t in found} >= {
        ("t_cascade", "project_id", False),
        ("t_setnull", "project_id", True),
        ("t_noaction", "project_id", False),
    }
    assert "t_two_hop" not in {t.table for t in found}  # points at t_cascade, not projects


async def test_ordinary_tables_are_cleared_and_counted_and_set_null_tables_are_retained(engine):
    """Edited in 1.2: the foundation deleted all three; a SET NULL table is now detached."""
    pid = await seed(engine)
    async with unit_of_work(engine) as session:
        removed, retained = await delete_project(session, "alpha")
    assert (removed, retained) == (2 + 1, 3)  # the two-hop row went by cascade, not counted
    for table in ("t_cascade", "t_noaction", "t_two_hop"):
        assert await count(engine, table) == 0
    assert await count(engine, "t_setnull") == 3
    assert await count(engine, "t_setnull WHERE project_id IS NULL") == 3
    assert await count(engine, f"t_setnull WHERE project_id = {pid}") == 0


async def test_a_missing_project_is_none(engine):
    async with unit_of_work(engine) as session:
        assert await delete_project(session, "ghost") is None


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


async def test_key_declared_without_a_column_is_found(storage_engine):
    """``REFERENCES projects`` (no column) means the primary key; PRAGMA reports ``to`` as None."""
    async with storage_engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE t_bare (id INTEGER PRIMARY KEY, "
                "owner INTEGER REFERENCES projects ON DELETE SET NULL)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE t_named (id INTEGER PRIMARY KEY, "
                "owner INTEGER REFERENCES projects(id) ON DELETE SET NULL)"
            )
        )
    async with storage_engine.connect() as conn:
        found = await conn.run_sync(_scoped_tables)
    assert {(t.table, t.column, t.retained) for t in found if t.table not in KNOWN} == {
        ("t_bare", "owner", True),
        ("t_named", "owner", True),
    }


async def test_a_table_added_later_with_set_null_is_retained_with_no_code_change(storage_engine):
    async with storage_engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE later (id INTEGER PRIMARY KEY, project_name TEXT, "
                "project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL)"
            )
        )
    async with unit_of_work(storage_engine) as session:
        project = await get_or_create_project(session, "alpha")
        await session.execute(
            text("INSERT INTO later (project_name, project_id) VALUES ('alpha', :p)"),
            {"p": project.id},
        )
    async with unit_of_work(storage_engine) as session:
        assert await delete_project(session, "alpha") == (0, 1)
    assert (
        await count(storage_engine, "later WHERE project_id IS NULL AND project_name='alpha'") == 1
    )


async def test_a_veto_after_the_detach_leaves_everything_as_it_was(engine):
    pid = await seed(engine)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TRIGGER veto BEFORE DELETE ON projects "
                "BEGIN SELECT RAISE(ABORT, 'vetoed'); END"
            )
        )
    with pytest.raises(Exception, match="vetoed"):
        async with unit_of_work(engine) as session:
            await delete_project(session, "alpha")
    assert await count(engine, f"t_setnull WHERE project_id = {pid}") == 3
    assert await count(engine, "projects") == 1
    assert await count(engine, "t_cascade") == 2


async def test_a_table_name_with_a_double_quote_is_introspected_and_detached(storage_engine):
    async with storage_engine.begin() as conn:
        await conn.execute(
            text(
                'CREATE TABLE "weird""name" (id INTEGER PRIMARY KEY, '
                "project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL)"
            )
        )
    async with unit_of_work(storage_engine) as session:
        project = await get_or_create_project(session, "alpha")
        await session.execute(
            text('INSERT INTO "weird""name" (project_id) VALUES (:p)'), {"p": project.id}
        )
    async with storage_engine.connect() as conn:
        found = await conn.run_sync(_scoped_tables)
    assert [(t.table, t.retained) for t in found if t.table not in KNOWN] == [('weird"name', True)]
    async with unit_of_work(storage_engine) as session:
        assert await delete_project(session, "alpha") == (0, 1)


# --- shapes the convention cannot serve are refused, naming the table -------------------------


async def make(engine, ddl):
    async with engine.begin() as conn:
        await conn.execute(text(ddl))


async def test_a_table_mixing_set_null_and_cascade_keys_to_projects_is_refused(storage_engine):
    await make(
        storage_engine,
        "CREATE TABLE t_mixed (id INTEGER PRIMARY KEY, "
        "kept INTEGER REFERENCES projects(id) ON DELETE SET NULL, "
        "lost INTEGER REFERENCES projects(id) ON DELETE CASCADE)",
    )
    async with unit_of_work(storage_engine) as session:
        await get_or_create_project(session, "alpha")
    async with storage_engine.connect() as conn:
        with pytest.raises(StorageError, match="t_mixed.*SET NULL.*CASCADE"):
            await conn.run_sync(_scoped_tables)
    with pytest.raises(StorageError, match="t_mixed"):
        async with unit_of_work(storage_engine) as session:
            await delete_project(session, "alpha")
    assert await count(storage_engine, "projects") == 1  # nothing was removed


async def test_two_keys_with_the_same_rule_are_still_fine(storage_engine):
    await make(
        storage_engine,
        "CREATE TABLE t_twin (id INTEGER PRIMARY KEY, "
        "a INTEGER REFERENCES projects(id) ON DELETE SET NULL, "
        "b INTEGER REFERENCES projects(id) ON DELETE SET NULL)",
    )
    async with storage_engine.connect() as conn:
        found = await conn.run_sync(_scoped_tables)
    assert {(t.column, t.retained) for t in found if t.table == "t_twin"} == {
        ("a", True),
        ("b", True),
    }


async def test_a_composite_key_to_projects_is_refused(storage_engine):
    await make(
        storage_engine,
        "CREATE TABLE t_composite (id INTEGER PRIMARY KEY, a INTEGER, b INTEGER, "
        "FOREIGN KEY (a, b) REFERENCES projects(id, name) ON DELETE SET NULL)",
    )
    async with storage_engine.connect() as conn:
        with pytest.raises(StorageError, match="t_composite.*composite"):
            await conn.run_sync(_scoped_tables)


async def test_a_not_null_column_with_set_null_is_refused(storage_engine):
    await make(
        storage_engine,
        "CREATE TABLE t_notnull (id INTEGER PRIMARY KEY, "
        "project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE SET NULL)",
    )
    async with storage_engine.connect() as conn:
        with pytest.raises(StorageError, match="t_notnull.*NOT NULL"):
            await conn.run_sync(_scoped_tables)

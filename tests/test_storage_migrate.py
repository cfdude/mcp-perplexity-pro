"""Task 5.2: the programmatic migration runner (local-storage 'Versioned migrations' and
'Backup before migrating')."""

import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mcp_perplexity_pro.storage.engine import database_path
from mcp_perplexity_pro.storage.migrate import (
    MIGRATIONS_DIR,
    MigrationError,
    backup_path,
    current_revision,
    downgrade,
    head_revision,
    migrate,
    migration_lock,
)

ADD_NOTES = """
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("notes", sa.Column("id", sa.Integer(), primary_key=True))


def downgrade():
    op.drop_table("notes")
"""

BOOM = """
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("half_done", sa.Column("id", sa.Integer(), primary_key=True))
    op.execute("INSERT INTO projects (name) VALUES ('added-by-failing-migration')")
    raise RuntimeError("boom in migration")


def downgrade():
    pass
"""

SLOW = ADD_NOTES.replace("def upgrade():", "def upgrade():\n    import time\n    time.sleep(0.7)")


@pytest.fixture
def scripts(tmp_path):
    """Factory: a scratch copy of the real migrations plus extra version files."""

    def make(**extra: str) -> Path:
        target = tmp_path / f"scripts-{len(list(tmp_path.glob('scripts-*')))}"
        shutil.copytree(MIGRATIONS_DIR, target, ignore=shutil.ignore_patterns("__pycache__"))
        for name, source in extra.items():
            (target / "versions" / f"{name}.py").write_text(source)
        return target

    return make


def _snapshot(db_file):
    """Schema and rows (not bytes: WAL files legitimately change)."""
    conn = sqlite3.connect(db_file)
    try:
        schema = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
        rows = {
            name: conn.execute(f'SELECT * FROM "{name}" ORDER BY 1').fetchall()
            for (kind, name, _sql) in schema
            if kind == "table"
        }
        return schema, rows
    finally:
        conn.close()


def _tables(db_file):
    conn = sqlite3.connect(db_file)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _add_project(db_file, name):
    conn = sqlite3.connect(db_file)
    conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()


def test_head_is_the_four_digit_initial_revision():
    assert head_revision() == "0001"
    assert [p.name for p in (MIGRATIONS_DIR / "versions").glob("*.py")] == ["0001_initial.py"]


def test_fresh_database_reaches_head(make_settings):
    settings = make_settings()
    result = migrate(settings)
    db = database_path(settings.data_dir)
    assert result.applied == ("0001",)
    assert result.from_revision is None
    assert current_revision(db) == head_revision() == "0001"
    assert "projects" in _tables(db)
    assert result.backup is None  # nothing to back up


def test_second_migrate_is_a_no_op(make_settings):
    settings = make_settings()
    migrate(settings)
    again = migrate(settings)
    assert again.applied == ()
    assert again.backup is None


def test_projects_name_is_case_sensitive_unique(make_settings):
    settings = make_settings()
    migrate(settings)
    db = database_path(settings.data_dir)
    _add_project(db, "Alpha")
    _add_project(db, "alpha")  # different case is a different project
    with pytest.raises(sqlite3.IntegrityError):
        _add_project(db, "Alpha")


def test_upgrade_downgrade_upgrade_round_trip(make_settings, scripts):
    settings = make_settings()
    loc = scripts(**{"0002_add_notes": ADD_NOTES})
    migrate(settings, script_location=loc)
    db = database_path(settings.data_dir)
    _add_project(db, "kept")
    assert {"projects", "notes"} <= _tables(db)

    result = downgrade(settings, script_location=loc)
    assert result.applied == ("0002",)
    assert current_revision(db) == "0001"
    assert "notes" not in _tables(db)
    kept = sqlite3.connect(db).execute("SELECT name FROM projects").fetchall()
    assert kept == [("kept",)]  # earlier data intact

    migrate(settings, script_location=loc)
    assert current_revision(db) == "0002"
    assert "notes" in _tables(db)


def test_initial_migration_downgrade_drops_projects(make_settings):
    settings = make_settings()
    migrate(settings)
    downgrade(settings, "base")
    db = database_path(settings.data_dir)
    assert "projects" not in _tables(db)
    assert current_revision(db) is None


def test_database_from_the_future_is_refused_unchanged(make_settings, scripts):
    settings = make_settings()
    migrate(settings, script_location=scripts(**{"0002_add_notes": ADD_NOTES}))
    db = database_path(settings.data_dir)
    _add_project(db, "precious")
    before = _snapshot(db)

    with pytest.raises(MigrationError) as err:
        migrate(settings)  # the real code only knows 0001
    assert "0002" in str(err.value)
    assert "0001" in str(err.value)
    assert _snapshot(db) == before
    assert not list(settings.data_dir.glob("backup-*"))


def test_failing_migration_keeps_schema_rows_and_names_itself(make_settings, scripts):
    settings = make_settings()
    migrate(settings)
    db = database_path(settings.data_dir)
    _add_project(db, "precious")
    before = _snapshot(db)

    with pytest.raises(MigrationError) as err:
        migrate(settings, script_location=scripts(**{"0002_boom": BOOM}))
    assert "0002_boom.py" in str(err.value)
    assert "boom in migration" in str(err.value)
    assert _snapshot(db) == before
    assert current_revision(db) == "0001"
    backup = backup_path(settings.data_dir, "0001")
    assert backup.exists()
    old = sqlite3.connect(backup).execute("SELECT name FROM projects").fetchall()
    assert old == [("precious",)]


def test_failing_migration_on_a_fresh_database_leaves_it_empty(make_settings, scripts):
    settings = make_settings()
    loc = scripts(**{"0002_boom": BOOM})
    with pytest.raises(MigrationError, match=r"0002_boom\.py"):
        migrate(settings, script_location=loc)
    db = database_path(settings.data_dir)
    assert _tables(db) == set()  # 0001 rolled back too: one transaction
    assert current_revision(db) is None


def test_backup_exists_after_upgrading_a_non_empty_database(make_settings, scripts):
    settings = make_settings()
    migrate(settings)
    db = database_path(settings.data_dir)
    _add_project(db, "before-upgrade")
    # an earlier backup of the same revision is replaced, not kept
    backup_path(settings.data_dir, "0001").write_bytes(b"stale garbage")

    result = migrate(settings, script_location=scripts(**{"0002_add_notes": ADD_NOTES}))
    backup = backup_path(settings.data_dir, "0001")
    assert result.backup == backup
    conn = sqlite3.connect(backup)
    try:
        assert "notes" not in {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert conn.execute("SELECT name FROM projects").fetchall() == [("before-upgrade",)]
    finally:
        conn.close()
    assert oct(backup.stat().st_mode & 0o777) == "0o600"


def test_lock_wait_is_bounded(tmp_path):
    with migration_lock(tmp_path, timeout=5):
        start = time.monotonic()
        with pytest.raises(MigrationError, match="Timed out"):
            with migration_lock(tmp_path, timeout=0.3):
                pass
        assert time.monotonic() - start < 3


CHILD = """
import json, sys
from pathlib import Path
from mcp_perplexity_pro.settings import Settings
from mcp_perplexity_pro.storage.migrate import migrate
data_dir, scripts, gate = sys.argv[1:4]
while not Path(gate).exists():
    pass
r = migrate(Settings(api_key="x", data_dir=data_dir), script_location=Path(scripts))
print(json.dumps({"applied": list(r.applied), "to": r.to_revision}))
"""


def test_two_processes_starting_together_apply_exactly_once(tmp_path, scripts):
    loc = scripts(**{"0002_slow": SLOW})
    data_dir = tmp_path / "shared"
    gate = tmp_path / "go"
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", CHILD, str(data_dir), str(loc), str(gate)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    time.sleep(1.0)  # both interpreters are imported and spinning on the gate
    gate.touch()
    outputs = []
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
        outputs.append(json.loads(out.strip().splitlines()[-1]))
    assert sorted(len(o["applied"]) for o in outputs) == [0, 2]  # one applied, one waited
    assert all(o["to"] == "0002" for o in outputs)
    assert current_revision(database_path(data_dir)) == "0002"

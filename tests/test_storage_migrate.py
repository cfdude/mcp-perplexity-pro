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
from alembic.script import ScriptDirectory
from migration_support import real_chain

from mcp_perplexity_pro.storage.engine import database_path
from mcp_perplexity_pro.storage.migrate import (
    MIGRATIONS_DIR,
    MigrationError,
    _config,
    backup_path,
    current_revision,
    downgrade,
    head_revision,
    migrate,
    migration_lock,
)

# The scratch revisions sit one past the REAL head, computed, so adding a real revision never
# makes them collide with it.
HEAD = head_revision()
NXT = f"{int(HEAD) + 1:04d}"

ADD_NOTES = """
import sqlalchemy as sa
from alembic import op

revision = "{revision}"
down_revision = "{down_revision}"
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

revision = "{revision}"
down_revision = "{down_revision}"
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


def scratch(slug: str, template: str) -> dict[str, str]:
    """``scripts(**scratch("add_notes", ADD_NOTES))``: a scratch revision one past the real head."""
    source = template.replace("{revision}", NXT).replace("{down_revision}", HEAD)
    return {f"{NXT}_{slug}": source}


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
        # sqlite_sequence outlives a dropped AUTOINCREMENT table; it is SQLite's, not ours
        return {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not r[0].startswith("sqlite_")
        }
    finally:
        conn.close()


def _add_project(db_file, name):
    conn = sqlite3.connect(db_file)
    conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()


def test_migration_files_are_named_contiguously_and_match_their_revision_ids():
    """Every versions/*.py is ``NNNN_slug.py``, numbered 0001.. without gaps, chained in order."""
    import re

    files = sorted(p.name for p in (MIGRATIONS_DIR / "versions").glob("*.py"))
    assert files, "no migrations found"
    for name in files:
        assert re.fullmatch(r"\d{4}_[a-z0-9_]+\.py", name), f"bad migration file name {name!r}"
    numbers = [int(name[:4]) for name in files]
    assert numbers == list(range(1, len(files) + 1)), f"not contiguous from 0001: {files}"

    script = ScriptDirectory.from_config(_config(MIGRATIONS_DIR))
    chain = list(reversed(list(script.walk_revisions())))  # base -> head
    assert [r.revision for r in chain] == [f"{n:04d}" for n in numbers]
    assert chain[0].down_revision is None
    for previous, current in zip(chain, chain[1:], strict=False):
        assert current.down_revision == previous.revision
    assert head_revision() == f"{numbers[-1]:04d}"


def test_every_migration_is_reversible_walking_head_to_base_and_back(make_settings):
    settings = make_settings()
    db = database_path(settings.data_dir)
    migrate(settings)
    head = head_revision()
    assert current_revision(db) == head
    while current_revision(db) is not None:  # one downgrade per revision proves each works
        before = current_revision(db)
        result = downgrade(settings)  # default: the latest revision
        assert result.applied == (before,)
    assert _tables(db) <= {"alembic_version"}  # nothing a migration made is left behind
    migrate(settings)
    assert current_revision(db) == head


def test_fresh_database_reaches_head(make_settings):
    settings = make_settings()
    result = migrate(settings)
    db = database_path(settings.data_dir)
    assert result.applied == tuple(real_chain())
    assert result.from_revision is None
    assert current_revision(db) == head_revision() == HEAD
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
    loc = scripts(**scratch("add_notes", ADD_NOTES))
    migrate(settings, script_location=loc)
    db = database_path(settings.data_dir)
    _add_project(db, "kept")
    assert {"projects", "notes"} <= _tables(db)

    result = downgrade(settings, script_location=loc)
    assert result.applied == (NXT,)
    assert current_revision(db) == HEAD
    assert "notes" not in _tables(db)
    kept = sqlite3.connect(db).execute("SELECT name FROM projects").fetchall()
    assert kept == [("kept",)]  # earlier data intact

    migrate(settings, script_location=loc)
    assert current_revision(db) == NXT
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
    migrate(settings, script_location=scripts(**scratch("add_notes", ADD_NOTES)))
    db = database_path(settings.data_dir)
    _add_project(db, "precious")
    before = _snapshot(db)

    with pytest.raises(MigrationError) as err:
        migrate(settings)  # the real code only knows the real head
    assert NXT in str(err.value)
    assert HEAD in str(err.value)
    assert _snapshot(db) == before
    assert not list(settings.data_dir.glob("backup-*"))


def test_failing_migration_keeps_schema_rows_and_names_itself(make_settings, scripts):
    settings = make_settings()
    migrate(settings)
    db = database_path(settings.data_dir)
    _add_project(db, "precious")
    before = _snapshot(db)

    with pytest.raises(MigrationError) as err:
        migrate(settings, script_location=scripts(**scratch("boom", BOOM)))
    assert f"{NXT}_boom.py" in str(err.value)
    assert "boom in migration" in str(err.value)
    assert _snapshot(db) == before
    assert current_revision(db) == HEAD
    backup = backup_path(settings.data_dir, HEAD)
    assert backup.exists()
    old = sqlite3.connect(backup).execute("SELECT name FROM projects").fetchall()
    assert old == [("precious",)]


def test_failing_migration_on_a_fresh_database_leaves_it_empty(make_settings, scripts):
    settings = make_settings()
    loc = scripts(**scratch("boom", BOOM))
    with pytest.raises(MigrationError, match=rf"{NXT}_boom\.py"):
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
    backup_path(settings.data_dir, HEAD).write_bytes(b"stale garbage")

    result = migrate(settings, script_location=scripts(**scratch("add_notes", ADD_NOTES)))
    backup = backup_path(settings.data_dir, HEAD)
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


def test_current_revision_of_a_non_database_file_is_a_migration_error(tmp_path):
    bad = tmp_path / "perplexity.db"
    bad.write_text("not a database\n" * 100)
    with pytest.raises(MigrationError, match="perplexity.db"):
        current_revision(bad)


def test_unusable_lock_file_is_a_migration_error(tmp_path):
    with pytest.raises(MigrationError, match="migrate.lock"):
        with migration_lock(tmp_path / "missing-dir"):
            pass


def test_unwritable_backup_target_is_a_migration_error(make_settings, tmp_path):
    from mcp_perplexity_pro.storage.migrate import _backup

    settings = make_settings()
    migrate(settings)
    db_file = database_path(settings.data_dir)
    with pytest.raises(MigrationError, match="backup"):
        _backup(db_file, tmp_path / "no-such-dir", "0001")


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
data_dir, scripts, ready, gate = sys.argv[1:5]
Path(ready).touch()  # imports done: this process is ready to race
while not Path(gate).exists():
    pass
r = migrate(Settings(api_key="x", data_dir=data_dir), script_location=Path(scripts))
print(json.dumps({"applied": list(r.applied), "to": r.to_revision,
                  "backup": str(r.backup) if r.backup else None}))
"""


def _wait_for_files(paths, timeout=30):
    deadline = time.monotonic() + timeout
    while not all(p.exists() for p in paths):
        assert time.monotonic() < deadline, (
            f"never appeared: {[p for p in paths if not p.exists()]}"
        )
        time.sleep(0.01)


def test_two_processes_on_a_non_empty_database_apply_once_and_back_up_once(
    tmp_path, scripts, make_settings
):
    """Both processes start from a database at the real head holding rows, so the backup path runs.

    The lock is what makes the outcome one backup of the OLD schema: without it the second
    process also backs up (same file, same temp name) while the first is mid-migration.
    """
    data_dir = tmp_path / "shared"
    settings = make_settings(data_dir=data_dir)
    migrate(settings)  # the real migrations: the real head
    db = database_path(data_dir)
    for name in ("one", "two", "three"):
        _add_project(db, name)
    loc = scripts(**scratch("slow", SLOW))
    gate = tmp_path / "go"
    ready = [tmp_path / "ready-0", tmp_path / "ready-1"]
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", CHILD, str(data_dir), str(loc), str(r), str(gate)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for r in ready
    ]
    _wait_for_files(ready)  # both interpreters are imported and spinning on the gate
    gate.touch()
    outputs = []
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
        outputs.append(json.loads(out.strip().splitlines()[-1]))

    assert sorted(len(o["applied"]) for o in outputs) == [0, 1]  # exactly one applied the new one
    assert all(o["to"] == NXT for o in outputs)
    assert sorted(o["backup"] is not None for o in outputs) == [False, True]  # one backup
    assert current_revision(db) == NXT

    backup = backup_path(data_dir, HEAD)
    assert [o["backup"] for o in outputs if o["backup"]] == [str(backup)]
    conn = sqlite3.connect(backup)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert "notes" not in {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)
        assert conn.execute("SELECT name FROM projects ORDER BY name").fetchall() == [
            ("one",),
            ("three",),
            ("two",),
        ]
    finally:
        conn.close()
    assert not list(data_dir.glob("*.tmp"))  # no half-written backup left behind


def test_an_existing_loose_lock_file_is_tightened_to_owner_only(tmp_path):
    lock = tmp_path / "migrate.lock"
    lock.write_bytes(b"")
    lock.chmod(0o644)
    with migration_lock(tmp_path):
        assert oct(lock.stat().st_mode & 0o777) == "0o600"
    assert oct(lock.stat().st_mode & 0o777) == "0o600"

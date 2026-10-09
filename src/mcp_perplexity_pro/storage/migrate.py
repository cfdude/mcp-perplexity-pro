"""Programmatic Alembic runner (design D10).

``migrate()`` runs before the async engine exists, on a synchronous ``sqlite3`` engine, and:

1. takes an exclusive file lock (``migrate.lock`` in the data directory, bounded wait) so two
   server processes sharing a data directory cannot migrate at once; the second waits, then
   finds nothing to do;
2. refuses a database whose recorded revision this code does not know (newer than the code),
   touching nothing;
3. copies a database that has a recorded revision to ``backup-<revision>.db`` with SQLite's
   online backup API (a plain file copy can be inconsistent while WAL content is outstanding),
   replacing any earlier backup of that revision;
4. runs the migrations inside one ``BEGIN IMMEDIATE`` transaction (SQLite DDL is
   transactional), so a failing migration rolls everything back and the previous schema and
   rows survive; the error names the failing migration file.
"""

from __future__ import annotations

import fcntl
import os
import sqlite3
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from mcp_perplexity_pro.storage.engine import (
    BEGIN_OPTION,
    FILE_MODE,
    StorageError,
    create_sync_engine,
    prepare_data_dir,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
LOCK_FILENAME = "migrate.lock"
LOCK_TIMEOUT = 60.0


class MigrationError(StorageError):
    """A migration failed, or the database cannot be migrated by this code."""


@dataclass(frozen=True)
class MigrationResult:
    from_revision: str | None
    to_revision: str | None
    applied: tuple[str, ...]  # revision ids this call applied, in order
    backup: Path | None  # backup written by this call, if any


def backup_path(data_dir: Path, revision: str) -> Path:
    return Path(data_dir) / f"backup-{revision}.db"


def _config(script_location: Path, connection=None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(script_location).replace("%", "%%"))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def head_revision(script_location: Path | None = None) -> str | None:
    return ScriptDirectory.from_config(
        _config(script_location or MIGRATIONS_DIR)
    ).get_current_head()


@contextmanager
def migration_lock(data_dir: Path, timeout: float = LOCK_TIMEOUT) -> Iterator[None]:
    """Exclusive cross-process lock; waits up to ``timeout`` seconds then raises."""
    lock_file = Path(data_dir) / LOCK_FILENAME
    try:
        fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, FILE_MODE)
    except OSError as exc:
        raise MigrationError(f"Cannot open migration lock file {lock_file}: {exc}") from exc
    deadline = time.monotonic() + timeout
    try:
        try:
            if os.fstat(fd).st_mode & 0o077:  # a lock file left loose by an earlier version
                os.fchmod(fd, FILE_MODE)
        except OSError as exc:
            raise MigrationError(f"Cannot secure migration lock file {lock_file}: {exc}") from exc
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise MigrationError(
                        f"Timed out after {timeout:g}s waiting for another process to finish "
                        f"migrating the database (lock file {lock_file})"
                    ) from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the flock


def current_revision(db_file: Path) -> str | None:
    """The revision recorded in the database, or ``None`` for an unmigrated one."""
    try:
        conn = sqlite3.connect(db_file)
        try:
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            if not has_table:
                return None
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        # also the parent of OperationalError, so tell a transient lock from a non-database file
        hint = (
            "Is it a SQLite database?"
            if "not a database" in str(exc).lower()
            else "The database may be locked or damaged."
        )
        raise MigrationError(
            f"Cannot read database {db_file}: {exc}. {hint} Nothing was changed."
        ) from exc


def _backup(db_file: Path, data_dir: Path, revision: str) -> Path:
    target = backup_path(data_dir, revision)
    tmp = target.with_suffix(".db.tmp")
    try:
        tmp.unlink(missing_ok=True)
        os.close(os.open(tmp, os.O_RDWR | os.O_CREAT | os.O_TRUNC, FILE_MODE))
        src = sqlite3.connect(db_file)
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        os.replace(tmp, target)  # replaces an existing backup of this revision
    except (sqlite3.Error, OSError) as exc:
        raise MigrationError(
            f"Cannot write backup {target} of {db_file}: {exc}. The database was not changed."
        ) from exc
    return target


def _failing_migration(exc: BaseException, script_location: Path) -> str | None:
    """File name of the migration script the exception was raised in, if any."""
    versions = (script_location / "versions").resolve()
    name = None
    for frame in traceback.extract_tb(exc.__traceback__):
        path = Path(frame.filename).resolve()
        if path.parent == versions:
            name = path.name
    return name


def _run(
    settings,
    direction: str,
    target: str,
    script_location: Path,
    lock_timeout: float,
) -> MigrationResult:
    db_file = prepare_data_dir(settings.data_dir)
    data_dir = db_file.parent
    script = ScriptDirectory.from_config(_config(script_location))
    head = script.get_current_head()

    with migration_lock(data_dir, lock_timeout):
        current = current_revision(db_file)
        if current is not None:
            try:
                known = script.get_revision(current) is not None
            except Exception:
                known = False
            if not known:
                raise MigrationError(
                    f"Database {db_file} is at revision {current!r}, which this version of the "
                    f"code does not know (newest known revision: {head!r}). Refusing to start; "
                    "upgrade mcp-perplexity-pro or restore a matching backup. The database "
                    "was not changed."
                )
        if direction == "upgrade" and current == head:
            return MigrationResult(current, current, (), None)

        backup = _backup(db_file, data_dir, current) if current is not None else None

        engine: Engine = create_sync_engine(db_file, settings.db_busy_timeout)
        conn = engine.connect().execution_options(**{BEGIN_OPTION: "IMMEDIATE"})
        cfg = _config(script_location, conn)
        try:
            with conn.begin():  # one transaction: any failure rolls back every step
                if direction == "upgrade":
                    command.upgrade(cfg, target)
                else:
                    command.downgrade(cfg, target)
        except Exception as exc:
            name = _failing_migration(exc, script_location)
            where = f"Migration {name}" if name else "Migration"
            kept = f"revision {current!r}" if current else "an empty schema"
            note = f"; backup: {backup}" if backup else ""
            raise MigrationError(
                f"{where} failed: {exc}. The database was left at {kept}{note}."
            ) from exc
        finally:
            conn.close()
            engine.dispose()
        return MigrationResult(
            current, current_revision(db_file), tuple(cfg.attributes.get("applied", ())), backup
        )


def migrate(
    settings, *, script_location: Path | None = None, lock_timeout: float = LOCK_TIMEOUT
) -> MigrationResult:
    """Bring the database under ``settings.data_dir`` to the latest revision."""
    return _run(settings, "upgrade", "head", script_location or MIGRATIONS_DIR, lock_timeout)


def downgrade(
    settings,
    target: str = "-1",
    *,
    script_location: Path | None = None,
    lock_timeout: float = LOCK_TIMEOUT,
) -> MigrationResult:
    """Reverse migrations down to ``target`` (default: the latest one); used by tests and ops."""
    return _run(settings, "downgrade", target, script_location or MIGRATIONS_DIR, lock_timeout)

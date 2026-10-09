"""Engine construction and data-directory preparation (design D10).

Everything the server persists lives in one SQLite file under ``Settings.data_dir``. The
directory is owner-only (0700) and so is the database file, so the WAL and shared-memory files
SQLite derives from it are owner-only too. Nothing is ever written to the working directory.

Transactions are explicit: the driver's implicit-BEGIN behaviour is switched off and a ``BEGIN``
is emitted when SQLAlchemy begins a transaction, ``BEGIN IMMEDIATE`` when the connection was
asked for a write (execution option ``sqlite_begin="IMMEDIATE"``). Taking the write lock up
front is what lets ``busy_timeout`` apply; a read-then-write transaction in WAL mode otherwise
fails at once with ``SQLITE_BUSY``.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

DB_FILENAME = "perplexity.db"
DIR_MODE = 0o700
FILE_MODE = 0o600
BEGIN_OPTION = "sqlite_begin"


class StorageError(Exception):
    """The local data directory or database cannot be used; the message says why."""


def database_path(data_dir: Path) -> Path:
    return Path(data_dir) / DB_FILENAME


def prepare_data_dir(data_dir: Path) -> Path:
    """Create ``data_dir`` (0700) and an empty owner-only database file; return the file path.

    An existing directory with any group or other access is tightened to 0700; if that is not
    possible startup fails naming the directory.
    """
    data_dir = Path(data_dir)
    try:
        data_dir.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        mode = stat.S_IMODE(data_dir.stat().st_mode)
        if mode & 0o077 or mode & 0o700 != 0o700:
            data_dir.chmod(DIR_MODE)
    except OSError as exc:
        raise StorageError(f"Cannot create or secure data directory {data_dir}: {exc}") from exc
    if not data_dir.is_dir():
        raise StorageError(f"Data directory {data_dir} is not a directory")
    db_file = database_path(data_dir)
    try:
        # Create with 0600 ourselves: sqlite3 would honour the umask (typically 0644).
        os.close(os.open(db_file, os.O_RDWR | os.O_CREAT, FILE_MODE))
        if stat.S_IMODE(db_file.stat().st_mode) & 0o077:
            db_file.chmod(FILE_MODE)
    except OSError as exc:
        raise StorageError(f"Cannot create or secure database file {db_file}: {exc}") from exc
    return db_file


def _install_connection_events(engine: Engine, busy_timeout: float) -> None:
    busy_ms = int(busy_timeout * 1000)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        # Take transaction control away from the driver; begin() below issues BEGIN.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={busy_ms}")  # first, so the next one can wait
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Any) -> None:
        kind = conn.get_execution_options().get(BEGIN_OPTION)
        conn.exec_driver_sql("BEGIN IMMEDIATE" if kind == "IMMEDIATE" else "BEGIN")


def create_sync_engine(db_file: Path, busy_timeout: float) -> Engine:
    """Synchronous engine (stdlib ``sqlite3``) used by the migration runner."""
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"timeout": busy_timeout})
    _install_connection_events(engine, busy_timeout)
    return engine


def create_engine_for(settings: Any) -> AsyncEngine:
    """Async engine for ``settings`` (needs ``data_dir`` and ``db_busy_timeout``).

    Prepares the data directory first; run migrations (``storage.migrate``) before using it.
    """
    db_file = prepare_data_dir(settings.data_dir)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        connect_args={"timeout": settings.db_busy_timeout},
    )
    _install_connection_events(engine.sync_engine, settings.db_busy_timeout)
    return engine

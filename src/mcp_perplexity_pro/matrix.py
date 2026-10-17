"""The model matrix: facts about each model, kept in one versioned file (design D1 to D3, D5).

Pure and synchronous apart from the lock wait: no network, no engine, no FastMCP. It holds

* the ``Matrix`` model (``model_matrix.json`` in the data directory: prices, availability and
  the accepted ``reasoning.effort`` levels of every model);
* ``load`` (the file, else the packaged baseline; a corrupt or newer file is never trusted);
* ``merge`` (a live model list into a matrix, with the guards that keep a truncated reply from
  marking models removed);
* ``write`` (a ``mkstemp`` file in the data directory replaced in one step, mode 0600);
* ``acquire_lock`` and ``update`` (the lock ``model_matrix.lock`` is polled with ``LOCK_NB`` and
  ``asyncio.sleep`` in the event loop, never in a thread, so a cancelled wait cannot take or hold
  it; the read, merge and write happen inside the lock in one thread call that releases it in its
  ``finally``).

The lock is never held across a network request, and nothing here writes except ``update``.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

VERSION = 1
FILENAME = "model_matrix.json"
LOCK_FILENAME = "model_matrix.lock"
LOCK_TIMEOUT = 5.0
LOCK_POLL = 0.05
FILE_MODE = 0o600
# A file larger than this is corrupt, not read: the packaged baseline is about 60 KB, so 4 MB
# is roughly 70 times the real thing and still small enough to parse without a memory spike.
MAX_FILE_BYTES = 4 * 1024 * 1024
BASELINE_RESOURCE = "data/model_matrix_baseline.json"
LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")

Status = Literal["available", "removed"]
Source = Literal["probe", "baseline", "unprobed"]


class Pricing(BaseModel):
    """Prices per million tokens, each null when the API did not report it."""

    model_config = ConfigDict(extra="ignore")

    input: float | None = None
    output: float | None = None
    cache_read: float | None = None
    cache_write: float | None = None


class Efforts(BaseModel):
    """The facts about a model's effort levels: how each was answered and what that adds up to.

    ``answers`` maps ``control`` and each answered level to its HTTP status and is kept while a
    probe is incomplete; ``accepted`` and ``refused`` are filled only for a whole answer set.
    """

    model_config = ConfigDict(extra="ignore")

    accepted: list[str] = Field(default_factory=list)
    refused: dict[str, int] = Field(default_factory=dict)
    answers: dict[str, int] = Field(default_factory=dict)
    probed_at: str | None = None
    source: Source = "unprobed"


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str | None = None
    status: Status = "available"
    pricing: Pricing = Field(default_factory=Pricing)
    first_seen: str
    last_seen: str
    probing_until: str | None = None
    efforts: Efforts = Field(default_factory=Efforts)


class Matrix(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = VERSION
    fetched_at: str
    models: dict[str, ModelEntry]


class LivePricing(Protocol):
    input: float | None
    output: float | None
    cache_read: float | None
    cache_write: float | None


class LiveModel(Protocol):
    """What ``merge`` reads of a listed model (``catalog.CatalogModel`` fits)."""

    id: str
    provider: str | None
    pricing: Any


def stamp(moment: datetime) -> str:
    """A UTC time as the file writes it: ``2026-10-17T20:11:03Z``."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow() -> datetime:
    return datetime.now(UTC)


def load_baseline() -> Matrix:
    """The matrix packaged with the code (read with ``importlib.resources``)."""
    return Matrix.model_validate_json(files(__package__).joinpath(BASELINE_RESOURCE).read_text())


# --- load -------------------------------------------------------------------------------------

LoadState = Literal["ok", "missing", "corrupt", "newer", "unreadable"]


@dataclass(frozen=True)
class Loaded:
    """A read of the matrix: the matrix to use, where it came from and what the file was.

    ``state`` is ``ok`` (a good file), ``missing``, ``corrupt`` (unreadable, empty or not a
    matrix: the first write renames it aside) or ``newer`` (a later version owns it: never
    written). ``unreadable`` means the file could not be read now (permissions, an I/O error, a
    directory in its place): it may be intact, so it is never renamed aside and nothing is written
    this round. Anything but ``ok`` yields the baseline, origin ``baseline``.
    """

    matrix: Matrix
    origin: Literal["file", "baseline"]
    state: LoadState


def load(path: Path, baseline: Matrix | None = None) -> Loaded:
    """Read ``path``, else the baseline. Reading never writes, renames or creates anything."""
    base = baseline if baseline is not None else load_baseline()
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return Loaded(base, "baseline", "missing")
    except OSError:  # EACCES, EIO, a directory: unreadable now is not the same as corrupt
        return Loaded(base, "baseline", "unreadable")
    if len(raw) > MAX_FILE_BYTES or not raw.strip():
        return Loaded(base, "baseline", "corrupt")
    try:
        doc = json.loads(raw)
    except (ValueError, RecursionError):  # a deeply nested file raises RecursionError
        return Loaded(base, "baseline", "corrupt")
    version = doc.get("version") if isinstance(doc, dict) else None
    if isinstance(version, int) and not isinstance(version, bool) and version > VERSION:
        return Loaded(base, "baseline", "newer")
    try:
        loaded = Matrix.model_validate(doc)
    except ValidationError:
        return Loaded(base, "baseline", "corrupt")
    if loaded.version != VERSION or not loaded.models:
        return Loaded(base, "baseline", "corrupt")
    return Loaded(loaded, "file", "ok")


# --- merge ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Merged:
    """The result of a merge. ``applied`` is false when a guard refused it (the matrix is then
    the input, unchanged, and ``warning`` says why)."""

    matrix: Matrix
    applied: bool
    warning: str | None = None


def _pricing(live: Any) -> Pricing:
    pricing = getattr(live, "pricing", None)
    return Pricing(**{k: getattr(pricing, k, None) for k in Pricing.model_fields})


def merge(current: Matrix, live: Iterable[LiveModel], baseline: Matrix, now: datetime) -> Merged:
    """Merge a live model list into ``current`` (the input is never modified).

    A new id is added ``available`` with the baseline's efforts when the baseline knows it, else
    ``unprobed``; a listed id gets the new price and ``last_seen``; a stored ``available`` id
    missing from the list becomes ``removed`` (row and efforts kept); a ``removed`` id that is
    listed again is ``available``. An empty list, or one that holds fewer than half of the stored
    ``available`` ids, changes nothing and warns: a truncated reply must not remove models.
    """
    listed = {m.id: m for m in live}
    stored_available = {i for i, e in current.models.items() if e.status == "available"}
    if not listed:
        return Merged(current, False, "the model list is empty; the matrix is unchanged")
    overlap = len(stored_available & listed.keys())
    if stored_available and overlap * 2 < len(stored_available):
        return Merged(
            current,
            False,
            f"the model list holds {overlap} of {len(stored_available)} stored available "
            "models and looks truncated; the matrix is unchanged",
        )
    seen = stamp(now)
    models = {i: e.model_copy(deep=True) for i, e in current.models.items()}
    for model_id, item in listed.items():
        entry = models.get(model_id)
        if entry is None:
            known = baseline.models.get(model_id)
            models[model_id] = ModelEntry(
                provider=item.provider,
                status="available",
                pricing=_pricing(item),
                first_seen=seen,
                last_seen=seen,
                probing_until=None,
                efforts=known.efforts.model_copy(deep=True) if known else Efforts(),
            )
        else:
            entry.status = "available"
            entry.pricing = _pricing(item)
            entry.last_seen = seen
            if item.provider:
                entry.provider = item.provider
    for model_id in stored_available - listed.keys():
        models[model_id].status = "removed"
    return Merged(Matrix(version=VERSION, fetched_at=seen, models=models), True)


# --- write ------------------------------------------------------------------------------------


def write(path: Path, value: Matrix) -> None:
    """Write ``value`` to ``path`` atomically: a temporary file in the same directory (mode
    0600), flushed to disk, then ``os.replace``. A failure leaves the old file and no temp file.
    Callers hold the lock (``update`` does)."""
    path = Path(path)
    data = value.model_dump_json(indent=1).encode() + b"\n"
    fd, tmp = tempfile.mkstemp(prefix="model_matrix.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), FILE_MODE)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:  # make the rename itself durable; a platform that refuses is not an error
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


# --- the lock ---------------------------------------------------------------------------------


class MatrixLockTimeout(Exception):
    """The lock was not free within the wait."""


class MatrixLock:
    """A held ``flock`` on ``model_matrix.lock``; closing the descriptor releases it."""

    def __init__(self, fd: int) -> None:
        self._fd: int | None = fd
        self._mutex = threading.Lock()  # release may come from the loop and from the thread

    def release(self) -> None:
        with self._mutex:
            fd, self._fd = self._fd, None
        if fd is not None:
            os.close(fd)


async def acquire_lock(data_dir: Path, timeout: float = LOCK_TIMEOUT) -> MatrixLock:
    """Take the exclusive lock, polling ``LOCK_NB`` with ``asyncio.sleep`` for at most
    ``timeout`` seconds. No thread is involved, so cancelling the wait ends it at once and the
    lock was never taken. Raises ``MatrixLockTimeout`` (or ``OSError`` if the file cannot be
    opened)."""
    lock_file = Path(data_dir) / LOCK_FILENAME
    fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, FILE_MODE)
    try:
        if os.fstat(fd).st_mode & 0o077:  # left loose by something else
            os.fchmod(fd, FILE_MODE)
    except OSError:
        pass
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return MatrixLock(fd)
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise MatrixLockTimeout(str(lock_file)) from None
                await asyncio.sleep(LOCK_POLL)
    except BaseException:  # a timeout, a cancel or an error: the descriptor is not kept
        os.close(fd)
        raise


# --- update: read, change and write under the lock --------------------------------------------

UpdateStatus = Literal["written", "unchanged", "lock_timeout", "newer_version", "skipped"]


@dataclass(frozen=True)
class Updated:
    """What ``update`` did. ``matrix`` is what was read inside the lock (before the change),
    or the written one for ``written``; ``None`` when the lock was never taken."""

    status: UpdateStatus
    matrix: Matrix | None = None


def _remove_stale_temp_files(data_dir: Path) -> None:
    for leftover in data_dir.glob("model_matrix.*.tmp"):  # only a killed writer leaves one
        try:
            leftover.unlink()
        except OSError:
            pass


class _Handoff:
    """Who releases the lock: the worker thread once it started, else ``update`` itself.

    A cancel can land after ``acquire_lock`` returned but before the thread starts (the queued
    work item is dropped, so its ``finally`` never runs). Under one mutex either the thread
    claims the lock (``claim``) or ``update`` abandons it (``abandon``), never both."""

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self._started = False
        self._abandoned = False

    def claim(self) -> bool:
        with self._mutex:
            if self._abandoned:
                return False
            self._started = True
            return True

    def abandon(self) -> bool:
        with self._mutex:
            if self._started:
                return False
            self._abandoned = True
            return True


def _update_locked(
    lock: MatrixLock,
    data_dir: Path,
    fn: Callable[[Matrix], Matrix | None],
    now: datetime,
    baseline: Matrix | None,
) -> Updated:
    try:
        path = data_dir / FILENAME
        _remove_stale_temp_files(data_dir)
        loaded = load(path, baseline)  # re-read INSIDE the lock: another server may have written
        if loaded.state == "newer":
            logger.warning("%s is from a newer version; it is left untouched", path)
            return Updated("newer_version", loaded.matrix)
        if loaded.state == "unreadable":  # maybe intact: do not rename it aside, do not write
            logger.warning("%s could not be read now; the write is skipped", path)
            return Updated("skipped", loaded.matrix)
        changed = fn(loaded.matrix)
        if changed is None:
            return Updated("unchanged", loaded.matrix)
        try:
            if path.exists() and not os.access(path, os.W_OK):
                raise PermissionError(f"{path} is read-only")
            if loaded.state == "corrupt":
                aside = path.with_name(f"{FILENAME}.corrupt-{now.astimezone(UTC):%Y%m%dT%H%M%SZ}")
                os.rename(path, aside)
                logger.warning("%s was unreadable or empty and was renamed to %s", path, aside)
            write(path, changed)
        except OSError as exc:
            logger.warning("the model matrix was not written: %s", exc)
            return Updated("skipped", loaded.matrix)
        return Updated("written", changed)
    finally:
        lock.release()


async def update(
    data_dir: Path,
    fn: Callable[[Matrix], Matrix | None],
    *,
    now: datetime | None = None,
    baseline: Matrix | None = None,
    timeout: float = LOCK_TIMEOUT,
) -> Updated:
    """Run ``fn`` on the stored matrix and write what it returns, under the lock.

    The lock wait is cancellable and bounded (``timeout``); the rest is ONE thread call that
    re-reads the file inside the lock, runs ``fn`` (return ``None`` to write nothing), writes and
    releases the lock in its ``finally``. A lock that cannot be taken, a newer-version file and
    a write that fails each log one warning and skip the write. A cancel during the thread call
    leaves the old or the new complete file (``os.replace``) and the thread still frees the lock.
    """
    data_dir = Path(data_dir)
    try:
        lock = await acquire_lock(data_dir, timeout)
    except MatrixLockTimeout:
        logger.warning("the model matrix lock was busy for %.1f s; the write is skipped", timeout)
        return Updated("lock_timeout")
    except OSError as exc:
        logger.warning("the model matrix lock could not be opened: %s", exc)
        return Updated("skipped")
    handoff = _Handoff()

    def work() -> Updated:
        if not handoff.claim():  # update() gave up before this thread ran
            return Updated("skipped")
        return _update_locked(lock, data_dir, fn, now or utcnow(), baseline)

    try:
        return await asyncio.to_thread(work)
    except BaseException:  # a cancel before the thread started leaves nobody else to release
        if handoff.abandon():
            lock.release()
        raise

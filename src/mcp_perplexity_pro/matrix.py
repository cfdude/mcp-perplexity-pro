"""The model matrix: facts about each model, kept in one versioned file (design D1 to D3, D5).

Pure and synchronous apart from the lock wait: no network, no engine, no FastMCP. It holds

* the ``Matrix`` model (``model_matrix.json`` in the data directory: prices, availability and
  the accepted ``reasoning.effort`` levels of every model);
* ``load`` (the file, else the packaged baseline; a corrupt or newer file is never trusted);
* ``merge`` (a live model list into a matrix, with the guards that keep a truncated reply from
  marking models removed);
* the input facts (``Inputs``: which of ``image`` and ``document`` a model accepts) and the one
  pure interface everything else reads them through: ``accepts``, ``models_accepting`` and
  ``preset_accepts``, plus the two classifiers ``model_not_served`` and ``is_named_refusal``;
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
import functools
import json
import logging
import os
import re
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
KINDS = ("image", "document")
# The only 400 bodies that mean "this model's route refuses that kind of input". The generic
# ``invalid request`` is NOT in the list: it is also what other failures say, so a kind it
# answered stays unknown. A probe may add a string here, nothing else may.
NAMED_REFUSALS = ("the selected model route does not support this document type or source",)
_NOT_SERVED = re.compile(
    r"validation failed: model\b.*\bis not supported", re.IGNORECASE | re.DOTALL
)
# Presets whose input kinds were verified live (2026-10-30); every other combination is unknown.
VERIFIED_PRESET_KINDS = {
    "fast": frozenset({"image", "document"}),
    "low": frozenset({"image"}),
    "medium": frozenset({"image", "document"}),
}

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


class Inputs(BaseModel):
    """The facts about the input kinds a model accepts (``image`` and ``document``; text is
    implicit). A kind is KNOWN when it is in ``accepted`` or ``refused``; ``source`` only labels
    where the newest answer came from and nothing reads it to decide. The per-kind objects are
    keyed by kind and absent means null or zero: ``attempts`` counts the requests sent for a kind
    and never resets, ``unanswered_rounds`` is the backoff counter and may reset."""

    model_config = ConfigDict(extra="ignore")

    accepted: list[str] = Field(default_factory=list)
    refused: dict[str, int] = Field(default_factory=dict)
    answers: dict[str, int] = Field(default_factory=dict)
    source: Source = "unprobed"
    probed_at: dict[str, str] = Field(default_factory=dict)
    last_attempt_at: dict[str, str] = Field(default_factory=dict)
    attempts: dict[str, int] = Field(default_factory=dict)
    unanswered_rounds: dict[str, int] = Field(default_factory=dict)
    retry_after: dict[str, str] = Field(default_factory=dict)


def attempted(inputs: Inputs, kind: str) -> bool:
    """The ONE predicate that says a kind was attempted: it has an answer, or a ``retry_after``,
    or ``attempts`` above 0. The merge, ``accepts`` and the probe selector all use it."""
    return (
        kind in inputs.accepted
        or kind in inputs.refused
        or inputs.retry_after.get(kind) is not None
        or inputs.attempts.get(kind, 0) > 0
    )


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str | None = None
    status: Status = "available"
    pricing: Pricing = Field(default_factory=Pricing)
    first_seen: str
    last_seen: str
    probing_until: str | None = None
    efforts: Efforts = Field(default_factory=Efforts)
    inputs: Inputs = Field(default_factory=Inputs)


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


@functools.cache
def cached_baseline() -> Matrix:
    """The packaged baseline, read once. Callers never modify it (``accepts`` and friends only
    read), so the shared object is safe; a test that changes the file clears this cache."""
    return load_baseline()


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


def _fill_inputs(entry: ModelEntry, known: ModelEntry | None) -> None:
    """Copy the baseline's answer for each kind that is NOT ``attempted`` in ``entry`` and that
    the baseline answers: that kind's answer only (never any bookkeeping of any kind, so a fill
    is not an attempt and a baseline-unknown kind keeps its backoff)."""
    if known is None:
        return
    mine, base = entry.inputs, known.inputs
    had_answers = bool(mine.accepted or mine.refused)
    for kind in KINDS:
        if attempted(mine, kind):
            continue
        if kind in base.accepted:
            mine.accepted = [k for k in KINDS if k in {*mine.accepted, kind}]
        elif kind in base.refused:
            mine.refused[kind] = base.refused[kind]
        else:
            continue
        if kind in base.answers:
            mine.answers[kind] = base.answers[kind]
        if kind in base.probed_at:
            mine.probed_at[kind] = base.probed_at[kind]
        if not had_answers:  # the label follows the lists: only a fill into an empty entry
            mine.source = "baseline"


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
                inputs=known.inputs.model_copy(deep=True) if known else Inputs(),
            )
        else:
            entry.status = "available"
            entry.pricing = _pricing(item)
            entry.last_seen = seen
            if item.provider:
                entry.provider = item.provider
            _fill_inputs(entry, baseline.models.get(model_id))
    for model_id in stored_available - listed.keys():
        models[model_id].status = "removed"
    return Merged(Matrix(version=VERSION, fetched_at=seen, models=models), True)


# --- the pure interface: what a model accepts -------------------------------------------------

Answer = Literal["yes", "no", "unknown"]


def _checked(kinds: Iterable[str]) -> frozenset[str]:
    kinds = frozenset(kinds)
    bad = kinds - set(KINDS)
    if bad:
        raise ValueError(f"unknown input kind {sorted(bad)[0]!r}; kinds are image and document")
    return kinds


def _kind_answer(entry: ModelEntry, known: ModelEntry | None, kind: str) -> Answer:
    inputs = entry.inputs
    if kind in inputs.accepted:
        return "yes"
    if kind in inputs.refused:
        return "no"
    if known is not None and not attempted(inputs, kind):  # the read-time baseline fallback
        if kind in known.inputs.accepted:
            return "yes"
        if kind in known.inputs.refused:
            return "no"
    return "unknown"


def accepts(model_id: str, kinds: Iterable[str], matrix: Matrix | None = None) -> Answer:
    """``yes`` when every kind is accepted, ``no`` when any is refused, else ``unknown``.

    Pure: reads ``matrix`` (the baseline when ``None``), never writes, never raises for an id (only
    a kind outside ``image`` and ``document`` raises ``ValueError``). A kind that is not
    ``attempted`` falls back to the baseline's answer for the same id. No kinds is ``yes``."""
    wanted = _checked(kinds)
    if not wanted:
        return "yes"
    base = cached_baseline()
    current = matrix if matrix is not None else base
    entry = current.models.get(model_id)
    if entry is None:
        return "unknown"
    answers = {_kind_answer(entry, base.models.get(model_id), kind) for kind in wanted}
    if "no" in answers:
        return "no"
    return "yes" if answers == {"yes"} else "unknown"


def models_accepting(kinds: Iterable[str], matrix: Matrix | None = None) -> set[str]:
    """The ``available`` model ids for which ``accepts`` is ``yes``; never one whose kind is
    unknown, never a ``removed`` one. No kinds gives every ``available`` model."""
    wanted = _checked(kinds)
    current = matrix if matrix is not None else cached_baseline()
    return {
        model_id
        for model_id, entry in current.models.items()
        if entry.status == "available" and accepts(model_id, wanted, current) == "yes"
    }


def preset_accepts(preset: str, kinds: Iterable[str]) -> Answer:
    """``yes`` for the combinations verified live on 2026-10-30, ``unknown`` for every other and
    never ``no``. No kinds is ``yes``."""
    wanted = _checked(kinds)
    if not wanted:
        return "yes"
    return "yes" if wanted <= VERIFIED_PRESET_KINDS.get(preset, frozenset()) else "unknown"


def model_not_served(status: int, message: str, model: str | None = None) -> bool:
    """True for the 400 ``validation failed: model ... is not supported``, and for a 404 or 410
    only when ``message`` names the requested ``model`` (so a job poll's 404 never matches). The
    one classifier of a gone model: the baseline rules, the input probe and the router call it."""
    if status == 400:
        return bool(_NOT_SERVED.search(message))
    if status in (404, 410):
        return bool(model) and model in message
    return False


def is_named_refusal(status: int, message: str) -> bool:
    """True only for a 400 whose whole message is in ``NAMED_REFUSALS``; the generic
    ``invalid request``, a 429 and any other 400 are never a refusal."""
    return status == 400 and message.strip() in NAMED_REFUSALS


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

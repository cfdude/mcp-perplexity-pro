"""The model matrix refresh task (design D4, D5): fetch the live list, merge it, write the file.

``MatrixState`` is the one mutable holder an ``AppContext`` carries (no module-level state): the
matrix tools read through ``snapshot()`` (loaded lazily on the first read, from the file else the
baseline, and never written by a read) and the serving process keeps its refresh ``task`` here.

The task is started only by a serving process (``build_server(..., matrix_refresh=True)``, the
lifespan) and is cancelled and awaited by the lifespan and by ``close_resources`` before the HTTP
client closes. It never blocks startup and never fails the server: every ``Exception`` except a
cancel becomes one redacted warning and the matrix stays as it was. Every write goes through
``matrix.update``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_perplexity_pro import matrix
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.redaction import redact_text

logger = logging.getLogger(__name__)


@dataclass
class MatrixState:
    """What the server knows about the matrix, and its refresh task.

    ``enabled`` is whether this process starts a task (set by ``build_server``). ``sleep`` and
    ``now`` are injectable so a test drives the interval and the leases without waiting.
    """

    data_dir: Path
    enabled: bool = False
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    now: Callable[[], datetime] = matrix.utcnow
    task: asyncio.Task[None] | None = None
    _loaded: matrix.Loaded | None = field(default=None, repr=False)
    _baseline: matrix.Matrix | None = field(default=None, repr=False)

    @property
    def baseline(self) -> matrix.Matrix:
        if self._baseline is None:
            self._baseline = matrix.load_baseline()
        return self._baseline

    def snapshot(self) -> matrix.Loaded:
        """The matrix to read: loaded from the file (else the baseline) on the first call and
        kept; only a refresh that wrote the file replaces it. Reading writes nothing."""
        if self._loaded is None:
            self._loaded = matrix.load(self.data_dir / matrix.FILENAME, self.baseline)
        return self._loaded

    def adopt(self, written: matrix.Matrix) -> None:
        """Make a matrix this process just wrote the one tools read (origin ``file``)."""
        self._loaded = matrix.Loaded(written, "file", "ok")


class ListUnavailable(Exception):
    """The live model list could not be fetched (the catalog returned its stale cache)."""


def describe(exc: BaseException) -> str:
    if isinstance(exc, PerplexityError):
        return f"[{exc.category}] {exc}"
    return f"{type(exc).__name__}: {exc}"


async def refresh_once(app: Any) -> None:
    """One refresh: a live list (never the catalog's cache), merged into the stored file."""
    state: MatrixState = app.matrix
    listing = await app.catalog.get(refresh=True)
    if listing.stale:  # a 5xx or a rate limit with a cached list: never merge old data
        raise ListUnavailable("the live model list could not be fetched; the matrix is unchanged")
    now = state.now()
    notes: list[str] = []

    def apply(current: matrix.Matrix) -> matrix.Matrix | None:
        merged = matrix.merge(current, listing.models, state.baseline, now)
        if not merged.applied:
            notes.append(merged.warning or "the merge was refused")
            return None
        return merged.matrix

    result = await matrix.update(app.settings.data_dir, apply, now=now, baseline=state.baseline)
    for note in notes:
        logger.warning("model matrix: %s", note)
    if result.status == "written" and result.matrix is not None:
        state.adopt(result.matrix)


async def run_refresh(app: Any) -> None:
    """The task body: refresh at start and then every ``matrix_refresh`` seconds (0: once)."""
    state: MatrixState = app.matrix
    settings = app.settings
    secrets = (settings.api_key.get_secret_value(),)
    interval = settings.matrix_refresh
    try:
        loaded = state.snapshot()
        logger.info(
            "model matrix refresh started: refresh=%s probe=%s matrix origin=%s fetched_at=%s",
            interval,
            settings.matrix_probe,
            loaded.origin,
            loaded.matrix.fetched_at,
        )
    except Exception as exc:  # a read that fails must not stop the refresh
        logger.warning("model matrix could not be read: %s", redact_text(describe(exc), secrets))
    while True:
        try:
            await refresh_once(app)
        except Exception as exc:  # CancelledError is a BaseException and passes
            logger.warning("model matrix refresh failed: %s", redact_text(describe(exc), secrets))
        if interval == 0:
            return
        await state.sleep(interval)


def start_task(app: Any) -> asyncio.Task[None]:
    """Create the refresh task (once: a running task is returned as it is)."""
    state: MatrixState = app.matrix
    if state.task is not None and not state.task.done():
        return state.task
    state.task = asyncio.create_task(run_refresh(app), name="model-matrix-refresh")
    return state.task


async def stop_task(state: MatrixState) -> None:
    """Cancel the refresh task and wait until it has ended. Safe with no task, and safe twice.

    ``asyncio.wait`` does not raise the task's cancellation, so only a cancel of the caller
    itself propagates. The task adds no wait of its own: its one shielded write is bounded by
    the lock wait.
    """
    task = state.task
    if task is None or task.done():
        if task is not None and not task.cancelled():
            task.exception()  # mark it retrieved
        return
    task.cancel()
    await asyncio.wait({task})
    if not task.cancelled():
        task.exception()
    logger.info("model matrix refresh stopped")

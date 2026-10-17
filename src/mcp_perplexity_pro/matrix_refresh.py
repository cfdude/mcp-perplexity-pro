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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from mcp_perplexity_pro import matrix
from mcp_perplexity_pro.agent import shielded_write
from mcp_perplexity_pro.costed import Recording, costed_call
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.models import AgentRun
from mcp_perplexity_pro.redaction import redact_text
from mcp_perplexity_pro.usage import agent_response_status, usage_from_agent_response

logger = logging.getLogger(__name__)

TOOL = "model_matrix"  # the usage events of a probe request: no MCP tool is behind them
PROBE_MODELS_PER_REFRESH = 10
PROBE_SPEND_CAP_NANO = 250_000_000  # $0.25, checked before each model (D6)
LEASE = timedelta(minutes=10)
CONTROL = "control"
ANSWER_KEYS = (CONTROL, *matrix.LEVELS)


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
    await probe_new(app)


# --- the probe (design D6) ----------------------------------------------------------------------

Outcome = Literal["accepted", "refused", "unanswered", "rate_limited"]


@dataclass
class Spend:
    """The reported cost of one refresh's probe requests so far (nano-USD)."""

    nano: int = 0


def _expired(lease: str | None, now: datetime) -> bool:
    """Whether a ``probing_until`` stamp no longer protects a model (absent or unreadable too)."""
    if lease is None:
        return True
    try:
        until = datetime.strptime(lease, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return True
    return until <= now


def _wants_probe(entry: matrix.ModelEntry, now: datetime) -> bool:
    return (
        entry.status == "available"
        and entry.efforts.source == "unprobed"
        and _expired(entry.probing_until, now)
    )


async def probe_request(app: Any, model: str, level: str | None, spend: Spend) -> Outcome:
    """One probe request, recorded as a usage event of tool ``model_matrix`` under no project.

    A completed 200 is ``accepted``; a 400 is ``refused`` (the caller counts it only after a
    completed control); a 429 is ``rate_limited`` (it ends the round); every other failure, a
    5xx, a timeout or a run that did not complete, is ``unanswered``.
    """

    def interpret(run: AgentRun) -> Recording | None:
        raw = run.model_dump(mode="json")
        status = agent_response_status(raw)
        if status is None:
            return None  # queued or in progress: no terminal state to record
        return Recording(
            status=status,
            usage=raw.get("usage"),  # the raw mapping: the recorder parses it
            model=raw.get("model") or model,
            request_id=raw.get("id"),
        )

    try:
        costed = await costed_call(
            app,
            tool=TOOL,
            api="agent",
            project=None,
            preset=None,
            call=lambda: app.client.probe_effort(model, level),
            record=interpret,
            unscoped=True,
        )
    except PerplexityError as exc:
        if exc.status == 429:
            return "rate_limited"
        return "refused" if exc.status == 400 else "unanswered"
    raw = costed.result.model_dump(mode="json")
    usage = usage_from_agent_response(raw.get("usage"))
    if usage.cost_source != "none":
        spend.nano += usage.cost_nano_usd
    return "accepted" if agent_response_status(raw) == "ok" else "unanswered"


async def _select(app: Any) -> list[str]:
    """Up to ten available, unprobed, unleased model ids, read under the lock."""
    state: MatrixState = app.matrix
    now = state.now()
    picked: list[str] = []

    def select(current: matrix.Matrix) -> None:
        picked.extend(i for i, e in current.models.items() if _wants_probe(e, now))
        del picked[PROBE_MODELS_PER_REFRESH:]

    await matrix.update(app.settings.data_dir, select, now=now, baseline=state.baseline)
    return picked


async def _take_lease(app: Any, model_id: str) -> dict[str, int] | None:
    """Write a 10-minute lease on one model under the lock, re-checking the row inside it.

    Returns the answers already stored (a partial probe), or ``None`` when the model should not
    be probed: it was probed elsewhere, leased by another server, removed, or the lease could not
    be written (without it a duplicate probe is possible, so none is made).
    """
    state: MatrixState = app.matrix
    now = state.now()
    answers: list[dict[str, int]] = []

    def lease(current: matrix.Matrix) -> matrix.Matrix | None:
        row = current.models.get(model_id)
        if row is None or not _wants_probe(row, now):
            return None
        copy = current.model_copy(deep=True)
        leased = copy.models[model_id]
        leased.probing_until = matrix.stamp(now + LEASE)
        answers.append(dict(leased.efforts.answers))
        return copy

    result = await matrix.update(app.settings.data_dir, lease, now=now, baseline=state.baseline)
    if result.status != "written" or result.matrix is None:
        return None
    state.adopt(result.matrix)
    return answers[0]


async def _finish(app: Any, model_id: str, answers: dict[str, int]) -> None:
    """Write a model's answers and clear its lease, under the lock. A whole answer set (the
    control and all six levels) also makes the model ``probe`` with its accepted and refused."""
    state: MatrixState = app.matrix
    now = state.now()

    def finish(current: matrix.Matrix) -> matrix.Matrix | None:
        if model_id not in current.models:
            return None
        copy = current.model_copy(deep=True)
        row = copy.models[model_id]
        row.efforts.answers = {**row.efforts.answers, **answers}
        row.probing_until = None
        known = row.efforts.answers
        if all(key in known for key in ANSWER_KEYS):
            row.efforts.accepted = [lv for lv in matrix.LEVELS if known[lv] == 200]
            row.efforts.refused = {lv: known[lv] for lv in matrix.LEVELS if known[lv] != 200}
            row.efforts.probed_at = matrix.stamp(now)
            row.efforts.source = "probe"
        return copy

    result = await matrix.update(app.settings.data_dir, finish, now=now, baseline=state.baseline)
    if result.status == "written" and result.matrix is not None:
        state.adopt(result.matrix)


async def probe_model(app: Any, model_id: str, spend: Spend) -> Literal["done", "skipped", "stop"]:
    """Probe one model: lease it, ask outside the lock, write what was answered, clear the lease.

    The control (no effort) goes first and every level after it, one at a time. The answers and
    the lease clearing are written in a ``finally`` and shielded, so a cancel, a 429 or an error
    never leaves a lease behind and never loses an answer already paid for."""
    answers = await _take_lease(app, model_id)
    if answers is None:
        return "skipped"
    outcome: Literal["done", "stop"] = "done"
    try:
        for key in ANSWER_KEYS:
            if key in answers:
                continue  # answered in an earlier refresh
            reply = await probe_request(app, model_id, None if key == CONTROL else key, spend)
            if reply == "accepted":
                answers[key] = 200
            elif reply == "rate_limited":
                outcome = "stop"
                break
            elif key == CONTROL:
                break  # no completed control: a level's answer would mean nothing
            elif reply == "refused":
                answers[key] = 400
            # unanswered: that level waits for the next refresh; the others are still asked
    finally:
        await shielded_write(_finish(app, model_id, answers))
    return outcome


async def probe_new(app: Any) -> None:
    """Probe the models neither the file nor the baseline knew (D6): at most ten, and none once
    the reported cost of this refresh reaches $0.25 (checked before each model)."""
    if app.settings.matrix_probe != "new":
        return
    spend = Spend()
    for model_id in await _select(app):
        if spend.nano >= PROBE_SPEND_CAP_NANO:
            logger.info("model matrix probe stopped: the spend cap was reached")
            break
        if await probe_model(app, model_id, spend) == "stop":
            logger.warning("model matrix probe stopped: the API rate-limited a request")
            break


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

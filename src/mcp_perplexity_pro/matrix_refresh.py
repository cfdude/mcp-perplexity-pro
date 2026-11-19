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
import contextlib
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
REFUSAL_TTL = timedelta(hours=24)  # a refused input kind is asked again after this (owner-editable)
UNANSWERED_ROUNDS = 2  # a kind unanswered this many rounds backs off
BACKOFF = timedelta(days=7)
FINISH_RETRY_WAIT = 1.0  # seconds before the one retry of a finish write that hit a busy lock
CONTROL = "control"
ANSWER_KEYS = (CONTROL, *matrix.LEVELS)
INPUT_KEYS = (
    CONTROL,
    *matrix.KINDS,
)  # the keys of an input round's answers, apart from ANSWER_KEYS


@dataclass
class InputRound:
    """One model's input probe in one round: the same-round control, what each wanted kind came
    to (``accepted``, ``refused`` or ``unanswered``) and which kinds a request was sent for
    (``attempts`` counts those and never resets)."""

    control: bool = False
    results: dict[str, str] = field(default_factory=dict)
    sent: set[str] = field(default_factory=set)


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
    # Per process, never written to the file. ``pending_answers`` holds the paid-for answers of a
    # model whose finish write failed (merged into its next lease and write); ``failed_models``
    # holds the models whose last round ended without a completed control or with an unanswered
    # level, so ``_select`` puts them behind the models that have not failed.
    pending_answers: dict[str, dict[str, int]] = field(default_factory=dict)
    failed_models: set[str] = field(default_factory=set)
    # The same two holders for the input probe, kept apart so a round that failed to finish
    # efforts does not mark inputs failed and the reverse.
    input_pending_answers: dict[str, list[InputRound]] = field(default_factory=dict)
    input_failed_models: set[str] = field(default_factory=set)
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


def _stamp_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _wants_efforts(entry: matrix.ModelEntry, now: datetime) -> bool:
    return (
        entry.status == "available"
        and entry.efforts.source == "unprobed"
        and _expired(entry.probing_until, now)
    )


def _wants_inputs(
    entry: matrix.ModelEntry, known: matrix.ModelEntry | None, now: datetime
) -> list[str]:
    """The input kinds worth a request now (per kind, design D6): a kind that is unknown (the
    baseline's answer for a kind not ``attempted`` counts as known) or refused for more than
    ``REFUSAL_TTL``, whose own ``retry_after`` has passed or is null, and that no attempt of the
    last ``LEASE`` has already tried."""
    if entry.status != "available" or not _expired(entry.probing_until, now):
        return []
    inputs = entry.inputs
    wanted: list[str] = []
    for kind in matrix.KINDS:
        last = _stamp_time(inputs.last_attempt_at.get(kind))
        if last is not None and now - last < LEASE:
            continue  # a recent unanswered attempt counts as probed
        if not _expired(inputs.retry_after.get(kind), now):
            continue
        answer = matrix.kind_answer(entry, known, kind)
        if answer == "unknown":
            wanted.append(kind)
        elif answer == "no":
            stamp_ = (
                inputs.probed_at.get(kind)
                if kind in inputs.refused
                else (known.inputs.probed_at.get(kind) if known else None)
            )
            probed = _stamp_time(stamp_)
            if probed is None or now - probed > REFUSAL_TTL:
                wanted.append(kind)
    return wanted


def _wants_probe(entry: matrix.ModelEntry, known: matrix.ModelEntry | None, now: datetime) -> bool:
    return _wants_efforts(entry, now) or bool(_wants_inputs(entry, known, now))


async def probe_request(
    app: Any,
    model: str,
    level: str | None,
    spend: Spend,
    *,
    call: Callable[[], Awaitable[AgentRun]] | None = None,
    inputs: bool = False,
) -> Outcome:
    """One probe request, recorded as a usage event of tool ``model_matrix`` under no project.

    A completed 200 is ``accepted``; a 400 is ``refused`` (the caller counts it only after a
    completed control); a 429 is ``rate_limited`` (it ends the round); every other failure, a
    5xx, a timeout or a run that did not complete, is ``unanswered``.

    ``call`` replaces the effort request (the input probe passes its own); ``inputs`` switches to
    the input rule: a 200 whose run status is ``completed`` or ``incomplete`` is ``accepted``
    (recorded with the status ``agent_response_status`` gives it, ``unexpected_response`` for
    ``incomplete``), a 400 is ``refused`` ONLY when ``matrix.is_named_refusal`` says so (a
    not-served 400, the generic ``invalid request`` and every other 400 are ``unanswered``), and
    a run that failed is ``unanswered``.
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
            call=call or (lambda: app.client.probe_effort(model, level)),
            record=interpret,
            unscoped=True,
        )
    except PerplexityError as exc:
        if exc.status == 429:
            return "rate_limited"
        if exc.status != 400:
            return "unanswered"
        if not inputs:
            return "refused"
        message = exc.api_message or str(exc)
        if matrix.model_not_served(400, message, model):
            return "unanswered"
        return "refused" if matrix.is_named_refusal(400, message) else "unanswered"
    raw = costed.result.model_dump(mode="json")
    usage = usage_from_agent_response(raw.get("usage"))
    if usage.cost_source != "none":
        spend.nano += usage.cost_nano_usd
    if inputs:
        return "accepted" if raw.get("status") in ("completed", "incomplete") else "unanswered"
    return "accepted" if agent_response_status(raw) == "ok" else "unanswered"


async def _select(app: Any) -> list[str]:
    """Up to ten available, unprobed, unleased model ids, read under the lock. Models that did
    not finish in this process come last (still eligible), so they cannot starve the others."""
    state: MatrixState = app.matrix
    now = state.now()
    failed = frozenset(state.failed_models)
    picked: list[str] = []

    input_failed = frozenset(state.input_failed_models)

    def select(current: matrix.Matrix) -> None:
        wanted = [
            i
            for i, e in current.models.items()
            if _wants_probe(e, state.baseline.models.get(i), now)
        ]

        def failed_before(i: str) -> bool:
            row = current.models[i]
            return (i in failed and _wants_efforts(row, now)) or (
                i in input_failed and bool(_wants_inputs(row, state.baseline.models.get(i), now))
            )

        wanted.sort(key=failed_before)  # stable: file order inside each group
        picked.extend(wanted[:PROBE_MODELS_PER_REFRESH])

    await matrix.update(app.settings.data_dir, select, now=now, baseline=state.baseline)
    return picked


@dataclass
class Lease:
    """What a leased model is owed, read inside the lock: ``efforts`` is the answers already
    stored (``None`` when the model's efforts need no probe) and ``kinds`` the input kinds to
    ask."""

    efforts: dict[str, int] | None
    kinds: list[str]


def _unanswered_kinds(state: MatrixState, model_id: str, kinds: list[str]) -> list[str]:
    """Drop the kinds a failed finish write of this process already holds an answer for."""
    done = {
        kind
        for rnd in state.input_pending_answers.get(model_id, [])
        for kind, result in rnd.results.items()
        if result in ("accepted", "refused")
    }
    return [k for k in kinds if k not in done]


async def _take_lease(app: Any, model_id: str, now: datetime) -> Lease | None:
    """Write a 10-minute lease on one model under the lock, re-checking the row inside it.

    Returns what the model is owed (the effort answers already stored for a partial probe, and
    the input kinds still to ask), or ``None`` when the model should not be probed: it was probed
    elsewhere, leased by another server, removed, or the lease could not be written (without it
    a duplicate probe is possible, so none is made). Answers a failed finish write of this
    process kept in memory are merged in, so they are not asked again.
    """
    state: MatrixState = app.matrix
    owed: list[Lease] = []

    def lease(current: matrix.Matrix) -> matrix.Matrix | None:
        row = current.models.get(model_id)
        if row is None:
            return None
        known = state.baseline.models.get(model_id)
        efforts = _wants_efforts(row, now)
        kinds = _unanswered_kinds(state, model_id, _wants_inputs(row, known, now))
        if not efforts and not kinds:
            return None
        copy = current.model_copy(deep=True)
        leased = copy.models[model_id]
        leased.probing_until = matrix.stamp(now + LEASE)
        owed.append(Lease(dict(leased.efforts.answers) if efforts else None, kinds))
        return copy

    result = await matrix.update(app.settings.data_dir, lease, now=now, baseline=state.baseline)
    if result.status != "written" or result.matrix is None:
        return None
    state.adopt(result.matrix)
    got = owed[0]
    if got.efforts is not None:
        got.efforts = {**got.efforts, **state.pending_answers.get(model_id, {})}
    return got


async def _release_lease(app: Any, model_id: str, until: str) -> None:
    """Clear this process's own lease (the stamp ``until``) on a model, under the lock; a lease
    another server wrote has a different stamp and is left alone."""
    state: MatrixState = app.matrix

    def clear(current: matrix.Matrix) -> matrix.Matrix | None:
        row = current.models.get(model_id)
        if row is None or row.probing_until != until:
            return None
        copy = current.model_copy(deep=True)
        copy.models[model_id].probing_until = None
        return copy

    result = await matrix.update(
        app.settings.data_dir, clear, now=state.now(), baseline=state.baseline
    )
    if result.status == "written" and result.matrix is not None:
        state.adopt(result.matrix)


async def _retry_pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _apply_input_round(inputs: matrix.Inputs, rnd: InputRound, now: datetime) -> None:
    """Write one input round into a model's inputs (per kind, design D6): every request sent
    counts in ``attempts`` and stamps ``last_attempt_at``; an answer replaces the old one and
    resets that kind's backoff; an unanswered kind keeps what it had, adds one to ITS
    ``unanswered_rounds`` and, at two, gets a ``retry_after`` 7 days ahead and a fresh count."""
    stamped = matrix.stamp(now)
    if rnd.control:
        inputs.answers[CONTROL] = 200
    for kind, result in rnd.results.items():
        if kind in rnd.sent:
            inputs.attempts[kind] = inputs.attempts.get(kind, 0) + 1
            inputs.last_attempt_at[kind] = stamped
        if result in ("accepted", "refused"):
            accepted = set(inputs.accepted)
            if result == "accepted":
                accepted.add(kind)
                inputs.refused.pop(kind, None)
                inputs.answers[kind] = 200
            else:
                accepted.discard(kind)
                inputs.refused[kind] = 400
                inputs.answers[kind] = 400
            inputs.accepted = [k for k in matrix.KINDS if k in accepted]
            inputs.probed_at[kind] = stamped
            inputs.unanswered_rounds.pop(kind, None)
            inputs.retry_after.pop(kind, None)
            inputs.source = "probe"
            continue
        rounds = inputs.unanswered_rounds.get(kind, 0) + 1
        if rounds >= UNANSWERED_ROUNDS:
            inputs.retry_after[kind] = matrix.stamp(now + BACKOFF)
            inputs.unanswered_rounds.pop(kind, None)
        else:
            inputs.unanswered_rounds[kind] = rounds


async def _finish(
    app: Any, model_id: str, answers: dict[str, int], rounds: list[InputRound] | None = None
) -> None:
    """Write a model's answers and clear its lease, under the lock. A whole effort answer set
    (the control and all six levels) also makes the model ``probe`` with its accepted and
    refused; ``answers`` empty leaves the efforts alone. ``rounds`` are the input rounds to
    apply (this one, and any a failed write of this process kept)."""
    state: MatrixState = app.matrix
    now = state.now()
    owed = [*state.input_pending_answers.get(model_id, []), *(rounds or [])]

    def finish(current: matrix.Matrix) -> matrix.Matrix | None:
        if model_id not in current.models:
            return None
        copy = current.model_copy(deep=True)
        row = copy.models[model_id]
        if answers:
            row.efforts.answers = {**row.efforts.answers, **answers}
            known = row.efforts.answers
            if all(key in known for key in ANSWER_KEYS):
                row.efforts.accepted = [lv for lv in matrix.LEVELS if known[lv] == 200]
                row.efforts.refused = {lv: known[lv] for lv in matrix.LEVELS if known[lv] != 200}
                row.efforts.probed_at = matrix.stamp(now)
                row.efforts.source = "probe"
        for rnd in owed:
            _apply_input_round(row.inputs, rnd, now)
        row.probing_until = None
        return copy

    result = await matrix.update(app.settings.data_dir, finish, now=now, baseline=state.baseline)
    if result.status == "lock_timeout":  # one retry: the answers were paid for
        await _retry_pause(FINISH_RETRY_WAIT)
        result = await matrix.update(
            app.settings.data_dir, finish, now=now, baseline=state.baseline
        )
    if result.status == "written" and result.matrix is not None:
        state.adopt(result.matrix)
    if result.status in ("written", "unchanged"):
        state.pending_answers.pop(model_id, None)
        state.input_pending_answers.pop(model_id, None)
        return
    if answers:
        state.pending_answers[model_id] = {**state.pending_answers.get(model_id, {}), **answers}
    if owed:
        state.input_pending_answers[model_id] = owed
    logger.warning(
        "model matrix: the answers for %s could not be written (%s); they are kept for the "
        "next refresh of this process",
        model_id,
        result.status,
    )


def _note_round(state: MatrixState, model_id: str, answers: dict[str, int]) -> None:
    """Remember a model whose round ended with an unanswered key (see ``failed_models``)."""
    if all(key in answers for key in ANSWER_KEYS):
        state.failed_models.discard(model_id)
    else:
        state.failed_models.add(model_id)


def _note_input_round(state: MatrixState, model_id: str, rnd: InputRound) -> None:
    """The same for the input probe, in its own set (``input_failed_models``)."""
    if any(result == "unanswered" for result in rnd.results.values()):
        state.input_failed_models.add(model_id)
    elif rnd.results:
        state.input_failed_models.discard(model_id)


async def probe_model(app: Any, model_id: str, spend: Spend) -> Literal["done", "skipped", "stop"]:
    """Probe one model: lease it, ask outside the lock, write what was answered, clear the lease.

    ONE text control goes first (no effort, no attachment) and serves both probes of the round:
    every effort level after it, then every wanted input kind, one request at a time. A control
    that did not complete leaves every level and kind unanswered. The answers and the lease
    clearing are written in a ``finally`` and shielded, so a cancel, a 429 or an error never
    leaves a lease behind and never loses an answer already paid for."""
    state: MatrixState = app.matrix
    now = state.now()
    until = matrix.stamp(now + LEASE)
    try:
        lease = await _take_lease(app, model_id, now)
    except BaseException:  # a cancel can land after the lease was written: clear our own stamp
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await shielded_write(_release_lease(app, model_id, until))
        raise
    if lease is None:
        return "skipped"
    efforts = lease.efforts is not None
    answers = lease.efforts if lease.efforts is not None else {}
    rnd = InputRound()
    outcome: Literal["done", "stop"] = "done"
    try:
        needs_control = bool(lease.kinds) or (efforts and CONTROL not in answers)
        control_ok = CONTROL in answers and not lease.kinds
        if needs_control:
            reply = await probe_request(app, model_id, None, spend)
            if reply == "accepted":
                answers[CONTROL] = 200
                rnd.control = control_ok = True
            elif reply == "rate_limited":
                outcome = "stop"
        if efforts and control_ok and outcome == "done":
            for key in ANSWER_KEYS:
                if key in answers:
                    continue  # answered in an earlier refresh
                reply = await probe_request(app, model_id, key, spend)
                if reply == "accepted":
                    answers[key] = 200
                elif reply == "rate_limited":
                    outcome = "stop"
                    break
                elif reply == "refused":
                    answers[key] = 400
                # unanswered: that level waits for the next refresh; the others are still asked
        if lease.kinds and outcome == "done":
            for kind in lease.kinds:
                if not rnd.control:  # the control did not complete: nothing is asked or refused
                    rnd.results[kind] = "unanswered"
                    continue
                rnd.sent.add(kind)
                reply = await probe_request(
                    app,
                    model_id,
                    None,
                    spend,
                    call=lambda k=kind: app.client.probe_input(model_id, k),
                    inputs=True,
                )
                if reply == "accepted":
                    rnd.results[kind] = "accepted"
                elif reply == "refused":
                    rnd.results[kind] = "refused"
                else:
                    rnd.results[kind] = "unanswered"
                    if reply == "rate_limited":
                        outcome = "stop"
                        break
    finally:
        if outcome == "done":  # a 429 says nothing about the model
            if efforts:
                _note_round(state, model_id, answers)
            _note_input_round(state, model_id, rnd)
        await shielded_write(
            _finish(
                app,
                model_id,
                answers if efforts else {},
                [rnd] if rnd.results or rnd.control else [],
            )
        )
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

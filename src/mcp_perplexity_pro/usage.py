"""Usage recording: money helpers, the usage types, the parsers and the recorder.

Money is an integer count of nano-USD (10^-9 USD) so sums are exact (design D2). A reported
float is converted through the text of its JSON value (``Decimal(repr(value))``), never by
multiplying a binary float, and rounds half up.

Caller sequence (design D6/D7; usage-recording "Recording order"). SQLite has ONE writer, and a
write unit of work (``BEGIN IMMEDIATE``) holds its lock until it commits, so a tool must:

1. validate the project name (pure, no database);
2. resolve the project in a short write unit that COMMITS before the call;
3. make the upstream call, holding NO write unit of work;
4. call ``record_usage`` (its own unit of work) while holding no write unit on that engine: invoked
   inside the caller's open one it waits the busy timeout for its own caller's lock, then returns
   ``False`` and the event is lost;
5. run the tool's own write unit last, so its rollback on failure never removes the event.

Deciding whether an Agent response is recorded (and as what) is ``agent_response_status``'s job
alone: every later epic calls it and never re-derives the rule.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import traceback
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from mcp_perplexity_pro.errors import ALL_CATEGORIES
from mcp_perplexity_pro.pricing import PRICES_AS_OF
from mcp_perplexity_pro.redaction import redact_text
from mcp_perplexity_pro.storage.models import Project, UsageEvent
from mcp_perplexity_pro.storage.projects import validate_project_name
from mcp_perplexity_pro.storage.session import unit_of_work

logger = logging.getLogger(__name__)

NANO_PER_USD = 10**9
# One cost above 1,000 USD is unusable: far above any single Perplexity call, and it keeps a
# SUM over about 9.2 million rows that all sit at the cap inside SQLite's signed 64-bit range.
MAX_COST_NANO = 10**12
# A trillion tokens in one call is five orders of magnitude above any context window.
MAX_TOKENS = 10**12

_NANO = Decimal(NANO_PER_USD)
_MAX_USD_BEFORE_ROUNDING = Decimal(MAX_COST_NANO + 1) / _NANO


def to_nano(value: object) -> int | None:
    """Convert a USD amount from a JSON response to nano-USD, or ``None`` when unusable.

    Total and bounded: a bool, NaN, infinity, negative, non-numeric value, a ``Decimal``
    operation that fails, an integer whose ``repr`` raises (thousands of digits) or a result
    above ``MAX_COST_NANO`` is unusable, and none of them raises. Catching ``Exception`` rather
    than only ``InvalidOperation`` is deliberate: ``repr(10**5000)`` raises ``ValueError``.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return None
        dollars = Decimal(repr(value))
        if dollars < 0 or dollars >= _MAX_USD_BEFORE_ROUNDING:
            return None
        nano = int((dollars * _NANO).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except Exception:  # total by contract; see the docstring
        return None
    return nano if 0 <= nano <= MAX_COST_NANO else None


def to_tokens(value: object) -> int | None:
    """A token count from a JSON response, or ``None`` unless a plain int in ``0..MAX_TOKENS``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= MAX_TOKENS else None


def format_usd(nano: int) -> str:
    """Exact decimal USD for ``nano`` nano-USD with trailing zeros trimmed (``1230000`` is
    ``"0.00123"``, ``0`` is ``"0"``)."""
    sign = "-" if nano < 0 else ""
    whole, fraction = divmod(abs(nano), NANO_PER_USD)
    digits = str(fraction).zfill(9).rstrip("0")
    return f"{sign}{whole}.{digits}" if digits else f"{sign}{whole}"


CostSource = Literal["reported", "computed", "none"]

# Integer facts of a call, by Usage field: token counts (to_tokens) and costs in nano-USD.
_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_tokens",
    "cache_creation_tokens",
    "cache_read_tokens",
    "reasoning_tokens",
)
_COST_FIELDS = (
    "input_cost_nano",
    "output_cost_nano",
    "cache_read_cost_nano",
    "cache_creation_cost_nano",
    "tool_calls_cost_nano",
)


@dataclass(frozen=True)
class ToolCallUsage:
    """One upstream tool (``search_web``) inside one call; ``None`` is unknown, never 0."""

    invocations: int | None = None
    cost_nano: int | None = None


@dataclass(frozen=True)
class Usage:
    """Parsed facts about one upstream call (design D7); every figure but the cost is optional.

    ``cost_nano_usd`` is 0 whenever ``cost_source`` is ``"none"`` (unknown, not free).
    ``raw`` is the usage object as received; the recorder sanitizes it before storing.
    """

    cost_nano_usd: int = 0
    cost_source: CostSource = "none"
    currency: str = "USD"
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
    reasoning_tokens: int | None = None
    input_cost_nano: int | None = None
    output_cost_nano: int | None = None
    cache_read_cost_nano: int | None = None
    cache_creation_cost_nano: int | None = None
    tool_calls_cost_nano: int | None = None
    tool_calls: dict[str, ToolCallUsage] = field(default_factory=dict)
    raw: dict | None = None
    price_table: str | None = None


def utcnow() -> datetime:
    """The current UTC time as a naive datetime with microseconds (how ``created_at`` is stored)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _cost_int(value: object) -> int | None:
    """A cost already in nano-USD: a plain int in ``0..MAX_COST_NANO``, else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= MAX_COST_NANO else None


def _clean_tool_calls(value: object, problems: list[str]) -> dict[str, ToolCallUsage]:
    if not isinstance(value, dict):
        problems.append("tool_calls")
        return {}
    cleaned = {}
    for name, entry in value.items():
        if not isinstance(name, str) or not isinstance(entry, ToolCallUsage):
            problems.append("tool_calls")
            continue
        cleaned[name] = ToolCallUsage(to_tokens(entry.invocations), _cost_int(entry.cost_nano))
    return cleaned


def computed_usage(cost_nano_usd: int, **facts: object) -> Usage:
    """A ``Usage`` whose cost the server derived from the documented prices (source
    ``computed``, stamped with ``PRICES_AS_OF``). Never raises.

    ``facts`` are other ``Usage`` fields (token counts, ``*_cost_nano``, ``tool_calls``, ``raw``,
    ``currency``); a malformed or unknown one becomes unknown and one warning is logged. A cost
    that is not a whole number of nano-USD in ``0..MAX_COST_NANO`` gives source ``none``.
    """
    try:
        problems: list[str] = []
        known = {f.name for f in fields(Usage)} - {
            "cost_nano_usd",
            "cost_source",
            "price_table",
        }
        kept: dict[str, object] = {}
        for name, value in facts.items():
            if name not in known:
                problems.append(name)
            elif name in _TOKEN_FIELDS:
                kept[name] = to_tokens(value)
            elif name in _COST_FIELDS:
                kept[name] = _cost_int(value)
            elif name == "tool_calls":
                kept[name] = _clean_tool_calls(value, problems)
            elif name == "raw":
                kept[name] = value if isinstance(value, dict) else None
            else:  # currency
                kept[name] = value if isinstance(value, str) else "USD"
            if name in _TOKEN_FIELDS + _COST_FIELDS and kept[name] is None and value is not None:
                problems.append(name)
        if problems:
            logger.warning("computed_usage: unusable facts ignored: %s", ", ".join(problems))
        cost = _cost_int(cost_nano_usd)
        if cost is None:
            logger.warning("computed_usage: unusable cost ignored")
            return Usage(**kept)
        return Usage(cost_nano_usd=cost, cost_source="computed", price_table=PRICES_AS_OF, **kept)
    except Exception:  # total by contract
        logger.warning("computed_usage: facts could not be read", exc_info=True)
        return Usage()


# usage.input_tokens_details / output_tokens_details / cost keys -> Usage fields
_INPUT_DETAILS = {
    "cache_creation_input_tokens": "cache_creation_tokens",
    "cache_read_input_tokens": "cache_read_tokens",
    "cached_tokens": "cached_tokens",
}
_OUTPUT_DETAILS = {"reasoning_tokens": "reasoning_tokens"}
_COST_KEYS = {
    "input_cost": "input_cost_nano",
    "output_cost": "output_cost_nano",
    "cache_read_cost": "cache_read_cost_nano",
    "cache_creation_cost": "cache_creation_cost_nano",
    "tool_calls_cost": "tool_calls_cost_nano",
}


def _read_figures(
    source: object, keys: dict[str, str], convert, label: str, problems: list[str]
) -> dict[str, int | None]:
    """Read ``keys`` from the mapping ``source`` through ``convert``.

    An absent or null key is unknown silently. A present but malformed key, or a ``source``
    that is not a mapping, is unknown and adds ``label`` to ``problems`` (names only, never
    values: the payload may hold anything).
    """
    out: dict[str, int | None] = dict.fromkeys(keys.values())
    if source is None:
        return out
    if not isinstance(source, Mapping):
        problems.append(label)
        return out
    for key, target in keys.items():
        value = source.get(key)
        if value is None:
            continue
        out[target] = convert(value)
        if out[target] is None:
            problems.append(f"{label}.{key}")
    return out


def _agent_tool_calls(details: object, problems: list[str]) -> dict[str, ToolCallUsage]:
    if details is None:
        return {}
    if not isinstance(details, Mapping):
        problems.append("tool_calls_details")
        return {}
    calls = {}
    for name, entry in details.items():
        if not isinstance(name, str):
            problems.append("tool_calls_details.<key>")
        elif not isinstance(entry, Mapping):
            problems.append(f"tool_calls_details.{_log_name(name)}")
            calls[name] = ToolCallUsage()
        else:
            invocations = to_tokens(entry.get("invocation"))
            cost = to_nano(entry.get("cost_usd"))
            if invocations is None and entry.get("invocation") is not None:
                problems.append(f"tool_calls_details.{_log_name(name)}.invocation")
            if cost is None and entry.get("cost_usd") is not None:
                problems.append(f"tool_calls_details.{_log_name(name)}.cost_usd")
            calls[name] = ToolCallUsage(invocations, cost)
    return calls


def _parse_agent(usage: Mapping) -> Usage:
    problems: list[str] = []
    figures: dict[str, object] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        figures.update(_read_figures(usage, {key: key}, to_tokens, "usage", problems))
    figures.update(
        _read_figures(
            usage.get("input_tokens_details"),
            _INPUT_DETAILS,
            to_tokens,
            "input_tokens_details",
            problems,
        )
    )
    figures.update(
        _read_figures(
            usage.get("output_tokens_details"),
            _OUTPUT_DETAILS,
            to_tokens,
            "output_tokens_details",
            problems,
        )
    )
    cost_source: CostSource = "none"
    cost_nano = 0
    currency = "USD"
    cost = usage.get("cost")
    if cost is not None and not isinstance(cost, Mapping):
        problems.append("cost")
    elif isinstance(cost, Mapping):
        reported = cost.get("currency")
        if isinstance(reported, str):
            currency = reported[:32]
        elif reported is not None:
            problems.append("cost.currency")
        if currency != "USD":
            problems.append("cost.currency (not USD, nothing converted)")
        else:
            figures.update(_read_figures(cost, _COST_KEYS, to_nano, "cost", problems))
            total = to_nano(cost.get("total_cost"))
            if total is not None:
                cost_nano, cost_source = total, "reported"
            elif cost.get("total_cost") is not None:
                problems.append("cost.total_cost")
    tool_calls = _agent_tool_calls(usage.get("tool_calls_details"), problems)
    if problems:
        logger.warning("agent usage: unusable figures treated as unknown: %s", "; ".join(problems))
    return Usage(
        cost_nano_usd=cost_nano,
        cost_source=cost_source,
        currency=currency,
        tool_calls=tool_calls,
        raw=dict(usage),
        **figures,
    )


def usage_from_agent_response(usage: object) -> Usage:
    """Parse the ``usage`` object of an Agent API response (design D7). Never raises.

    ``cost.total_cost`` is the cost when it converts (source ``reported``, 0 included); any
    malformed figure is unknown for that figure only, and one warning per call names the fields
    (never the values). ``None`` or a non-mapping is ``Usage()``. The recorder runs this itself
    for ``api="agent"``, so callers pass the raw mapping to ``record_usage`` and never parse.
    """
    if usage is None:
        return Usage()
    try:
        if not isinstance(usage, Mapping):
            logger.warning("agent usage: not a mapping (%s)", type(usage).__name__)
            return Usage()
        return _parse_agent(usage)
    except Exception:  # total by contract
        logger.warning("agent usage: could not be parsed", exc_info=True)
        return Usage()


def agent_response_status(response: object) -> str | None:
    """What a caller does with a decoded Agent API response body. Never raises.

    ``"ok"``: status ``completed`` (or absent) with a null ``error``, so record it.
    ``None``: status ``queued`` or ``in_progress`` (a background submit or a pending poll,
    which carry no usage), so do NOT record it: recording it as ``ok`` would occupy the dedupe key
    of the real terminal response (design D8).
    ``"unexpected_response"``: any other status, a non-null ``error`` or a non-mapping, so record
    it with that status and whatever usage it reports.

    Every caller uses this function instead of re-deriving the rule. Only ``completed`` and
    ``queued`` have been observed; ``in_progress`` and the failure statuses are from the docs.
    """
    try:
        if not isinstance(response, Mapping) or response.get("error") is not None:
            return "unexpected_response"
        status = response.get("status")
        if status is None or status == "completed":
            return "ok"
        if status in ("queued", "in_progress"):
            return None
        return "unexpected_response"
    except Exception:  # total by contract
        return "unexpected_response"


# --- The recorder (design D6, D7, D8) ---------------------------------------------------------

API_FAMILIES = ("agent", "search", "embeddings", "decisions")
VALID_STATUSES = frozenset({"ok", *ALL_CATEGORIES})
MAX_USAGE_JSON = 16384  # bytes; 32 times the recorded 501-byte Agent usage object
MAX_TEXT = 512  # characters kept of an identity string (ids, model names): far above any real one

# api -> parser turning a raw usage Mapping into a Usage. Each later epic adds its own entry
# after probing the live response; an api without one stores the mapping unpriced (source none).
# The entry calls through the module-level name so a test can replace the parser function itself.
_PARSERS: dict[str, Callable[[Mapping], Usage]] = {
    "agent": lambda usage: usage_from_agent_response(usage)
}


def _failure_text(exc: BaseException, secrets: Iterable[str]) -> str:
    """The exception and its traceback as text with secrets removed (a log filter may not be
    installed where this runs, and the text of a database error can echo bound values)."""
    rendered = "".join(traceback.format_exception(exc))
    return redact_text(rendered[-2000:], secrets)


def _safe(value: object, secrets: Iterable[str]) -> str:
    # Redact BEFORE cutting: a key straddling the cut would survive as a short prefix.
    return redact_text(repr(value), secrets)[:80]


def _text(value: object, secrets: Iterable[str]) -> str | None:
    """An identity string with secrets removed, or ``None`` for anything that is not a string.

    Redacted first and cut after, so a key straddling ``MAX_TEXT`` cannot leave a fragment."""
    return redact_text(value, secrets)[:MAX_TEXT] if isinstance(value, str) else None


def _log_name(name: object) -> str:
    """An upstream-supplied key name made safe for a log line: redacted, one printable line, at
    most 64 characters."""
    shown = redact_text(name, ()) if isinstance(name, str) else repr(name)
    return re.sub(r"[^\x20-\x7e]", "?", shown)[:64]


def _project_name(project: object, secrets: Iterable[str]) -> str | None:
    """The project name to store: validated by the same rule that creates projects and stored
    as written (a name that passes cannot hold a key, so redacting it would only corrupt valid
    names such as ``pplx-embeddings``). ``None`` for no project or one the rule refuses; the
    refusal is logged redacted and never raised."""
    if project is None:
        return None
    try:
        return validate_project_name(project)
    except Exception:  # PerplexityError, or anything odd a caller passed
        logger.warning("usage event project name ignored: %s", _safe(project, secrets))
        return None


def _marker(reason: str, size: int | None) -> str:
    return json.dumps({"_truncated": True, "_reason": reason, "_original_bytes": size})


def _redact_strings(value: object, secrets: Iterable[str]) -> object:
    """A copy of a JSON-like value with every string key and value redacted."""
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, dict):
        return {
            (redact_text(k, secrets) if isinstance(k, str) else k): _redact_strings(v, secrets)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_strings(v, secrets) for v in value]
    return value


def _usage_json(raw: object, secrets: Iterable[str]) -> str | None:
    """The usage object as strict, redacted JSON of at most ``MAX_USAGE_JSON`` bytes, else a
    marker object naming why it was not kept (design D6)."""
    if raw is None:
        return None
    try:
        serialized = json.dumps(raw, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError, RecursionError, OverflowError):
        return _marker("unserializable", None)
    size = len(serialized.encode())
    if size > MAX_USAGE_JSON:
        return _marker("oversize", size)
    try:
        # Redact the strings BEFORE serializing: json.dumps escapes non-ASCII, quotes and
        # backslashes, so a secret holding any of them no longer matches in the finished text.
        redacted = json.dumps(_redact_strings(raw, secrets), allow_nan=False, separators=(",", ":"))
        redacted = redact_text(redacted, secrets)  # keys and values the walk could not see
        json.loads(redacted)  # a secret holding a quote can break the text
    except (ValueError, TypeError, RecursionError, OverflowError):
        return _marker("unserializable", None)
    return redacted


def _tool_calls_json(calls: dict[str, ToolCallUsage], secrets: Iterable[str]) -> str | None:
    if not calls:
        return None
    body = {
        redact_text(name, secrets): {"invocations": c.invocations, "cost_nano": c.cost_nano}
        for name, c in calls.items()
    }
    text = json.dumps(body, separators=(",", ":"))
    if len(text.encode()) > MAX_USAGE_JSON:
        return _marker("oversize", len(text.encode()))
    return text


def _resolve_usage(usage: object, api: str, secrets: Iterable[str]) -> Usage:
    """``usage`` as a validated ``Usage``: a Mapping is parsed here, inside the guarded block."""
    if usage is None:
        return Usage()
    if isinstance(usage, Mapping):
        parser = _PARSERS.get(api)
        if parser is None:
            return Usage(raw=dict(usage))
        try:
            return parser(usage)
        except Exception as exc:  # a parser bug must never reach the tool
            logger.warning("usage parser for %r failed: %s", api, _failure_text(exc, secrets))
            return Usage()
    if isinstance(usage, Usage):
        return usage
    logger.warning("usage of type %s ignored", type(usage).__name__)
    return Usage()


def _event_values(parsed: Usage, secrets: Iterable[str]) -> dict[str, object]:
    """The cost and detail columns of ``parsed``, revalidated (a caller may build a ``Usage``)."""
    cost = _cost_int(parsed.cost_nano_usd)
    source = parsed.cost_source if parsed.cost_source in ("reported", "computed") else "none"
    # Never add a non-USD amount as USD; a computed cost must name the price table it used.
    if parsed.currency != "USD" or (source == "computed" and parsed.price_table is None):
        cost, source = 0, "none"
    if cost is None or source == "none":
        cost, source = 0, "none"
    values: dict[str, object] = {
        "cost_nano_usd": cost,
        "cost_source": source,
        "currency": _text(parsed.currency, secrets) or "USD",
        "price_table": _text(parsed.price_table, secrets) if source == "computed" else None,
        "tool_calls_json": _tool_calls_json(_clean_tool_calls(parsed.tool_calls, []), secrets),
        "usage_json": _usage_json(parsed.raw, secrets),
    }
    values.update({name: to_tokens(getattr(parsed, name)) for name in _TOKEN_FIELDS})
    values.update({name: _cost_int(getattr(parsed, name)) for name in _COST_FIELDS})
    return values


def _build_event(
    *,
    tool: object,
    api: object,
    status: object,
    usage: object,
    model: object,
    preset: object,
    request_id: object,
    project: object,
    latency_ms: object,
    secrets: tuple[str, ...],
    clock: Callable[[], datetime],
) -> dict[str, object] | None:
    """The row to insert, or ``None`` after logging why the event is refused."""
    if api not in API_FAMILIES:
        logger.warning("usage event refused: unknown api %s", _safe(api, secrets))
        return None
    if not isinstance(status, str) or status not in VALID_STATUSES:
        logger.warning("usage event refused: unknown status %s", _safe(status, secrets))
        return None
    if not isinstance(tool, str) or not tool:
        logger.warning("usage event refused: tool is not a name (%s)", _safe(tool, secrets))
        return None
    created = clock()
    if created.tzinfo is not None:
        created = created.astimezone(UTC).replace(tzinfo=None)
    return {
        "created_at": created,
        "tool": _text(tool, secrets),
        "api": api,
        "status": status,
        "latency_ms": to_tokens(latency_ms),
        "model": _text(model, secrets),
        "preset": _text(preset, secrets),
        "request_id": _text(request_id, secrets),
        "project_name": _project_name(project, secrets),
        **_event_values(_resolve_usage(usage, api, secrets), secrets),
    }


def _store_failure(exc: BaseException, secrets: Iterable[str]) -> str:
    """Why a write failed, without the usage payload (design D6). A SQLAlchemy error renders its
    ``[SQL: ...]`` and ``[parameters: ...]`` (every bound value), so only the exception type and
    the database driver's own message are logged for one."""
    if isinstance(exc, SQLAlchemyError):
        cause = getattr(exc, "orig", None)
        detail = f"{type(cause).__name__}: {cause}" if cause is not None else "no driver detail"
        return redact_text(f"{type(exc).__name__} ({detail})", secrets)[:500]
    return _failure_text(exc, secrets)


async def _store(engine: AsyncEngine, values: dict[str, object], secrets: tuple[str, ...]) -> bool:
    """Insert one event in its own unit of work. Never raises (``Exception``)."""
    try:
        async with unit_of_work(engine) as session:
            project_id = None
            if values["project_name"] is not None:  # a lookup: recording never creates a project
                project_id = (
                    await session.execute(
                        select(Project.id).where(Project.name == values["project_name"])
                    )
                ).scalar_one_or_none()
            result = await session.execute(
                insert(UsageEvent).values(**values, project_id=project_id).on_conflict_do_nothing()
            )
            stored = result.rowcount == 1
        if not stored:
            logger.debug("usage event for %s %s already recorded", values["api"], "response")
        return stored
    except Exception as exc:
        logger.warning("usage event not recorded: %s", _store_failure(exc, secrets))
        return False


async def record_usage(
    engine: AsyncEngine,
    *,
    tool: str,
    api: str,
    status: str = "ok",
    usage: Usage | Mapping | None = None,
    model: str | None = None,
    preset: str | None = None,
    request_id: str | None = None,
    project: str | None = None,
    latency_ms: int | None = None,
    secrets: Iterable[str] = (),
    clock: Callable[[], datetime] = utcnow,
) -> bool:
    """Store one usage event for a costed upstream call, best effort. Never raises.

    Runs after the upstream call, in its OWN unit of work, so it must be called while the caller
    holds no write unit of work on ``engine`` (SQLite has one writer: it would wait the busy
    timeout for its own caller's lock, fail and lose the event). Returns ``True`` when the event
    was stored; ``False`` when it was refused (unknown ``api`` or ``status``), a duplicate of an
    already recorded ``ok`` response, or recording failed (logged with secrets removed).

    ``usage`` is a parsed ``Usage``, the raw usage mapping (parsed here, inside the guarded block,
    by the parser registered for ``api``) or ``None``. The write is shielded from cancellation of
    the calling task: once the upstream call has returned the spend has happened, so a cancel
    that arrives now is re-raised only after the event is written.
    """
    secrets = tuple(s for s in secrets if isinstance(s, str) and s)
    try:
        values = _build_event(
            tool=tool,
            api=api,
            status=status,
            usage=usage,
            model=model,
            preset=preset,
            request_id=request_id,
            project=project,
            latency_ms=latency_ms,
            secrets=secrets,
            clock=clock,
        )
    except Exception as exc:
        logger.warning("usage event not recorded: %s", _failure_text(exc, secrets))
        return False
    if values is None:
        return False
    write = asyncio.ensure_future(_store(engine, values, secrets))
    try:
        return await asyncio.shield(write)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await asyncio.shield(write)  # let the write finish before the cancel moves on
        raise

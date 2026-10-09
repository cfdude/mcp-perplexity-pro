"""Usage recording: money helpers, the usage types, the parsers and the recorder.

Money is an integer count of nano-USD (10^-9 USD) so sums are exact (design D2). A reported
float is converted through the text of its JSON value (``Decimal(repr(value))``), never by
multiplying a binary float, and rounds half up.

Deciding whether an Agent response is recorded (and as what) is ``agent_response_status``'s job
alone: every later epic calls it and never re-derives the rule.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from mcp_perplexity_pro.pricing import PRICES_AS_OF

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
            problems.append(f"tool_calls_details.{name}")
            calls[name] = ToolCallUsage()
        else:
            invocations = to_tokens(entry.get("invocation"))
            cost = to_nano(entry.get("cost_usd"))
            if invocations is None and entry.get("invocation") is not None:
                problems.append(f"tool_calls_details.{name}.invocation")
            if cost is None and entry.get("cost_usd") is not None:
                problems.append(f"tool_calls_details.{name}.cost_usd")
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

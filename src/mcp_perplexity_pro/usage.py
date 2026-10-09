"""Usage recording: money helpers, the usage types, the parsers and the recorder.

Money is an integer count of nano-USD (10^-9 USD) so sums are exact (design D2). A reported
float is converted through the text of its JSON value (``Decimal(repr(value))``), never by
multiplying a binary float, and rounds half up.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

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

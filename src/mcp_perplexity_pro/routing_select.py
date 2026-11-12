"""The router's pure selector (routing-v2 design D3 to D6).

``select(...)`` picks ``(model, effort)`` for one call from dated evidence and the model matrix.
Pure: no network, database, file, clock, randomness or module state; the same arguments give the
same result in every process (``PYTHONHASHSEED`` included: nothing here iterates a set or a dict
where order could reach the result). The caller passes everything in, so a test passes small
literals.

Steps (D3): eligible shortlist models, the best class score, the contenders within the margin in
exact ``Decimal``, the lowest blended price among them, then the effort the tier asks for clipped
to the model's accepted levels. With nothing eligible the fallback chain of D6 runs: the default
fallback model, then the tier's documented preset, else ``invalid_request``.

``reason`` is at most 120 ASCII characters built from constants and counts, never prompt text.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal

from mcp_perplexity_pro import matrix as matrix_mod
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.routing_evidence import Evidence
from mcp_perplexity_pro.settings import ROUTER_MARGIN_DEFAULT

PRICE_WEIGHTS = (3, 1)  # blended price = (3 * input + 1 * output) / 4 per million tokens
MARGIN_POINTS = (
    ROUTER_MARGIN_DEFAULT  # 3.0, owner-approved 2026-11-11; PERPLEXITY_ROUTER_MARGIN overrides
)
TOOLS = ("ask", "chat")
LEVELS = matrix_mod.LEVELS  # ordered lowest to highest
# The level a tier asks for (D5). ``high`` and ``xhigh`` are never automatic: a call has a 120 s
# read timeout, and the tier never changes which model wins, only the effort.
TARGET_EFFORT = {"light": "low", "standard": "medium", "complex": "medium"}
# The documented preset of each tier (D6 rung c); it names no model.
TIER_PRESET = {"light": "fast", "standard": "low", "complex": "medium"}
REASON_MAX_LENGTH = 120
_CLASS_NAME = re.compile(r"[a-z][a-z_]{0,19}")

Accepts = Callable[[str, frozenset[str]], str]
PresetAccepts = Callable[[str, frozenset[str]], str]


@dataclass(frozen=True)
class Selection:
    """What ``select`` chose: a ``model`` (and the ``effort`` to send, or ``None``) or, for the
    last rung only, a ``preset`` and no model. ``selected_by`` is ``router`` or ``fallback``."""

    model: str | None
    effort: str | None
    reason: str
    selected_by: str
    preset: str | None = None


def blended_price(input_price: float, output_price: float) -> Decimal:
    """``(3 * input + 1 * output) / 4`` in exact decimal arithmetic (prices from their text)."""
    weight_in, weight_out = PRICE_WEIGHTS
    total = weight_in * Decimal(str(input_price)) + weight_out * Decimal(str(output_price))
    return total / (weight_in + weight_out)


def clip_effort(
    accepted: Iterable[str], target: str, *, lowest_fallback: bool = True
) -> str | None:
    """The highest accepted level not above ``target``, else (when ``lowest_fallback``) the lowest
    accepted level, else ``None`` (nothing is accepted)."""
    known = [level for level in LEVELS if level in set(accepted)]
    if not known:
        return None
    not_above = [level for level in known if LEVELS.index(level) <= LEVELS.index(target)]
    if not_above:
        return not_above[-1]
    return known[0] if lowest_fallback else None


def _effort_for(
    matrix: matrix_mod.Matrix, model_id: str, target: str, *, lowest_fallback: bool = True
) -> str | None:
    """The level to send for ``model_id``: none when the model is absent from the matrix or its
    efforts were never probed (an ``unprobed`` row has no facts to clip against)."""
    entry = matrix.models.get(model_id)
    if entry is None or entry.efforts.source == "unprobed":
        return None
    return clip_effort(entry.efforts.accepted, target, lowest_fallback=lowest_fallback)


def _class_label(task_class: str) -> str:
    return task_class if _CLASS_NAME.fullmatch(task_class) else "unknown"


def _reason(*parts: str) -> str:
    return "; ".join(parts).encode("ascii", "replace").decode("ascii")[:REASON_MAX_LENGTH]


def _number(value: Decimal) -> str:
    return f"{value:f}".rstrip("0").rstrip(".") or "0"


def select(
    task_class: str,
    tier: str,
    tool: str,
    evidence: Evidence,
    matrix: matrix_mod.Matrix,
    required_input: Iterable[str] = (),
    margin: Decimal | float | int | str = MARGIN_POINTS,
    search: bool | None = None,
    *,
    accepts: Accepts | None = None,
    preset_accepts: PresetAccepts | None = None,
) -> Selection:
    """Choose the model and effort for one call; raises ``PerplexityError`` (``invalid_request``)
    when no model rung and no preset rung can serve it.

    ``required_input`` is a set of ``image`` and ``document`` (empty means text only). A model is
    eligible only when ``accepts(model, kinds) == "yes"``: ``no``, ``unknown`` and unprobed are
    never substituted, and the fallback model and the preset rung are checked the same way
    (``preset_accepts``). The two functions are arguments so a test can stub them; by default
    they read ``matrix`` and the verified preset table of ``matrix``.
    """
    if tool not in TOOLS:
        raise ValueError(f"tool must be one of {TOOLS}")
    if tier not in TARGET_EFFORT:
        raise ValueError(f"tier must be one of {tuple(TARGET_EFFORT)}")
    kinds = frozenset(required_input)
    margin_points = margin if isinstance(margin, Decimal) else Decimal(str(margin))
    check_model: Accepts = accepts or (lambda m, k: matrix_mod.accepts(m, k, matrix))
    check_preset: PresetAccepts = preset_accepts or matrix_mod.preset_accepts
    label = _class_label(task_class)
    target = TARGET_EFFORT[tier]

    def usable(model_id: str) -> bool:
        entry = matrix.models.get(model_id)
        return (
            entry is not None
            and entry.status == "available"
            and (not kinds or check_model(model_id, kinds) == "yes")  # no kinds: always yes
        )

    # Step 1: the eligible shortlist models and their class scores.
    scored: list[tuple[Decimal, str]] = []
    for model_id in evidence.shortlist:
        if not usable(model_id):
            continue
        pricing = matrix.models[model_id].pricing
        if pricing.input is None or pricing.output is None:
            continue
        score = evidence.class_score(model_id, task_class)
        if score is not None:
            scored.append((score, model_id))

    if scored:
        # Steps 3 and 4: contenders within the margin; the lowest blended price wins, ties go to
        # the higher score, then the smaller id, so no dict or set order reaches the result.
        best = max(score for score, _ in scored)
        contenders = [(s, m) for s, m in scored if s >= best - margin_points]
        priced = [
            (blended_price(*_prices(matrix, m)), -s, m)  # -s: the higher score sorts first
            for s, m in contenders
        ]
        _, _, winner = min(priced)
        rule = "cheapest" if len(contenders) > 1 else "best score"
        reason = _reason(label, f"{len(contenders)} within {_number(margin_points)} pts", rule)
        return Selection(winner, _effort_for(matrix, winner, target), reason, "router")

    return _fallback(label, tier, target, kinds, search, evidence, matrix, usable, check_preset)


def _prices(matrix: matrix_mod.Matrix, model_id: str) -> tuple[float, float]:
    pricing = matrix.models[model_id].pricing
    assert pricing.input is not None and pricing.output is not None
    return pricing.input, pricing.output


def _fallback(
    label: str,
    tier: str,
    target: str,
    kinds: frozenset[str],
    search: bool | None,
    evidence: Evidence,
    matrix: matrix_mod.Matrix,
    usable: Callable[[str], bool],
    check_preset: PresetAccepts,
) -> Selection:
    """The chain of D6 after an empty eligible set: the default fallback model, then the tier's
    preset, else ``invalid_request``."""
    default = evidence.fallbacks["default"]
    if usable(default.model):
        # Its own level (``low``) is clipped like any level, but never raised: the rung exists
        # to be cheap, so no accepted level at or below it means no ``reasoning`` at all.
        effort = _effort_for(matrix, default.model, default.effort, lowest_fallback=False)
        reason = _reason(label, "no eligible model", "fallback default model")
        return Selection(default.model, effort, reason, "fallback")

    preset = TIER_PRESET[tier]
    searching = search is not False  # a preset always searches
    media_ok = not kinds or check_preset(preset, kinds) == "yes"
    if searching and media_ok:
        reason = _reason(label, "no eligible model", f"fallback preset {preset}")
        return Selection(None, None, reason, "fallback", preset=preset)

    problems: list[str] = []
    if kinds:
        names = " and ".join(sorted(kinds))
        problems.append(f"no routed model or preset is known to accept {names} input")
    if not searching:
        problems.append(
            "search is false, a preset always searches and no routed model is available"
        )
    raise PerplexityError("invalid_request", "; ".join(problems) + ".")

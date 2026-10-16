"""The Decisions-API tier classifier of dynamic routing (routing-decisions-classifier, D1 to D5).

``classify_dynamic`` asks the Decisions API one ``choice`` question (``tier``) over the prompt
and returns a ``rules.Classification``; the caller hands it to ``routing.resolve(...,
classification=)``, which owns the follow-up floor, the search-off rule and the reason caps.

* The request is one recorded costed call (``decisions.run_decide``, so no second recording
  sequence exists), made holding no write unit, and bounded by ``BOUND_SECONDS`` (retries
  included). The caller validates the project name first: a bad name is the caller's error and
  never a fallback.
* Any failure falls back to ``rules.classify`` and never fails the call. A real client cancel
  (``CancelledError``) is not a failure and propagates.
* A weak answer (strength under ``WEAK_BELOW``) takes the higher of the two tiers, a tie going
  to the Decisions tier.
* The prompt appears only in the request: reasons are built from constants, the tier, a
  probability and a failure category, and the log line names the category only.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp_perplexity_pro import decisions, rules
from mcp_perplexity_pro.decisions import DecideOptions, DecisionAnswer
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.rules import Classification
from mcp_perplexity_pro.settings import TIER_NAMES, Settings

logger = logging.getLogger(__name__)

CLASSIFIER = "decisions"
QUESTION = "tier"
BOUND_SECONDS = 3.0  # the request and its retries; a constant, not a setting
STATE_CHARS = 4000  # the prompt's first characters are the state sent
WEAK_BELOW = 0.5  # a majority of the probability mass; routing-eval-tuning owns the value
REASON_MAX_LENGTH = rules.REASON_MAX_LENGTH

# Final criteria (fixtures ``decisions_tier_*`` were captured with exactly these; a change here
# means re-capturing them, and ``tests/test_routing_decisions.py`` compares the two).
CRITERIA = {
    "light": "A short factual lookup with one clear answer, such as a current value or a date.",
    "standard": "An ordinary question that needs a sourced, explained answer but no deep analysis.",
    "complex": "An analytical, multi-part or long task that needs comparison, design or "
    "step-by-step reasoning.",
}


def _cap(reason: str) -> str:
    return reason.encode("ascii", "replace").decode("ascii")[:REASON_MAX_LENGTH]


def _from_rules(text: str, lead: str) -> Classification:
    """The rules' verdict, prefixed with why the Decisions answer was not used."""
    base = rules.classify(text)
    return Classification(
        tier=base.tier,
        reason=_cap(f"{lead}, rules: {base.reason}"),
        classifier=rules.CLASSIFIER,
        signals=base.signals,
    )


def _strength(answer: DecisionAnswer, choice: str) -> float | None:
    """The chosen option's probability, else ``confidence``, else ``None`` (unreadable)."""
    for name, probability in (answer.probabilities or {}).items():
        if name.strip().casefold() == choice and probability is not None:
            return probability
    return answer.confidence


def _read(answer: DecisionAnswer | None) -> tuple[str, float | None] | None:
    """``(tier, strength)`` of a readable answer, else ``None`` (also for an unknown tier)."""
    if answer is None or answer.type != "choice" or answer.choice is None:
        return None
    choice = answer.choice.strip().casefold()
    if choice not in TIER_NAMES:
        return None
    return choice, _strength(answer, choice)


def _decided(text: str, tier: str, strength: float | None) -> Classification:
    if strength is None:
        return Classification(tier, f"decisions: {tier}", CLASSIFIER)
    if strength >= WEAK_BELOW:
        return Classification(tier, f"decisions: {tier} ({strength:.2f})", CLASSIFIER)
    base = rules.classify(text)
    if TIER_NAMES.index(base.tier) > TIER_NAMES.index(tier):
        return Classification(
            base.tier,
            _cap(f"decisions weak ({tier} {strength:.2f}), rules: {base.reason}"),
            rules.CLASSIFIER,
            base.signals,
        )
    return Classification(tier, f"decisions: {tier} ({strength:.2f}, weak)", CLASSIFIER)


def wants_decider(
    settings: Settings,
    *,
    depth: str | None,
    tier: str | None,
    model: str | None,
    search: bool | None,
) -> bool:
    """Whether a call is classified by the Decisions API: dynamic mode with that classifier, no
    selector named and ``search`` not false. The caller still validates the call first."""
    return (
        settings.routing == "dynamic"
        and settings.classifier == CLASSIFIER
        and depth is None
        and tier is None
        and model is None
        and search is not False
    )


async def classify_dynamic(
    app: Any, text: str, *, project: str | None, tool: str
) -> Classification:
    """Classify ``text`` with the Decisions API, falling back to the rules on any failure.

    ``app`` is the ``AppContext``; ``tool`` is the name of the MCP tool whose call caused the
    request (its usage event's tool) and ``project`` that call's project (validated by the
    caller). Never raises except for a client cancel."""
    deadline = asyncio.get_running_loop().time() + BOUND_SECONDS
    try:
        body = decisions.build_request(
            DecideOptions(
                state=text[:STATE_CHARS],
                questions={QUESTION: {"type": "choice", "criteria": dict(CRITERIA)}},
            )
        )
    except PerplexityError:  # blank, or an image: the decider cannot read it
        return _from_rules(text, "prompt not classifiable")
    secrets = (app.settings.api_key.get_secret_value(),)
    try:
        costed = await decisions.run_decide(
            app, project=project, body=body, tool=tool, deadline=deadline
        )
    except PerplexityError as exc:
        category = exc.category
    except Exception as exc:  # never fatal: the call proceeds on the rules
        logger.warning("decisions classifier: unexpected %s", type(exc).__name__)
        category = "internal_error"
    else:
        digest = decisions.digest(costed.result, secrets, question_names=[QUESTION])
        read = _read(digest.answers.get(QUESTION))
        if read is None:
            logger.info("decisions classifier: answer unreadable")
            return _from_rules(text, "decisions answer unreadable")
        return _decided(text, *read)
    logger.info("decisions classifier failed: %s", category)
    return _from_rules(text, f"decisions failed ({category})")

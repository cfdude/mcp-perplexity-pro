"""The offline rules classifier of dynamic routing (routing-rules-v1, design D1 to D3).

``classify(text)`` returns a tier (``light``, ``standard`` or ``complex``), the signals that
fired and a short reason. Pure: no settings, network, database, clock or randomness, so the same
text gives the same result in every process. The reason is assembled from constants and counts,
never from the text, because prompts can hold secrets and the reason is returned and logged.

The thresholds and word lists below are starting points pinned by ``tests/test_rules.py`` and
by the labeled set ``tests/fixtures/routing_prompts.json``; they are not claims of accuracy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CLASSIFIER = "rules"

LENGTH_COMPLEX = 1200  # trimmed characters at or above which a text is complex
QUESTIONS_COMPLEX = 3  # questions plus numbered items at or above which a text is complex
VOCABULARY_COMPLEX = 2  # distinct analysis groups at or above which a text is complex
LIGHT_MAX_LENGTH = 120  # a lookup is at most this many trimmed characters
LIGHT_MAX_QUESTIONS = 1
REASON_MAX_LENGTH = 120

# One entry per word family: forms of one family count once.
ANALYSIS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("compare", "comparison"),
    ("evaluate", "evaluation"),
    ("trade-off", "trade-offs", "tradeoff", "tradeoffs"),
    ("pros and cons",),
    ("step by step",),
    ("root cause",),
    ("architecture",),
    ("in depth",),
    ("analyze", "analyse", "analysis"),
    ("critique",),
    ("derive",),
    ("prove",),
    ("design",),
    ("implications",),
)

LOOKUP_OPENINGS: tuple[str, ...] = (
    "what is",
    "what are",
    "who is",
    "who was",
    "when did",
    "when is",
    "where is",
    "how many",
    "how much",
    "define",
    "latest",
    "current",
    "price of",
)


def _phrase(term: str) -> str:
    return r"\s+".join(re.escape(word) for word in term.split())


# Whole words: not preceded or followed by a word character.
_GROUP_PATTERNS = tuple(
    re.compile(r"(?<!\w)(?:" + "|".join(_phrase(t) for t in group) + r")(?!\w)")
    for group in ANALYSIS_GROUPS
)
_LOOKUP = re.compile(r"(?:" + "|".join(_phrase(o) for o in LOOKUP_OPENINGS) + r")(?!\w)")
# An ASCII question mark counts only before whitespace or the end (so a URL query string does
# not); the full-width and Arabic ones count anywhere.
_QUESTION = re.compile(r"\?(?=\s|\Z)|[？؟]")
_NUMBERED_ITEM = re.compile(r"^[ \t]*[0-9]+[.)][ \t]", re.MULTILINE)


@dataclass(frozen=True)
class Classification:
    """A tier, who decided, the signals that fired (fixed order: vocabulary, length, questions,
    lookup) and a reason built from signal names and counts only."""

    tier: str
    reason: str
    classifier: str = CLASSIFIER
    signals: tuple[str, ...] = ()


def classify(text: str) -> Classification:
    """Classify ``text``; total, never raises on any string."""
    trimmed = text.strip()
    folded = trimmed.casefold()
    length = len(trimmed)

    terms = sum(1 for pattern in _GROUP_PATTERNS if pattern.search(folded))
    questions = len(_QUESTION.findall(trimmed))
    counted = questions + len(_NUMBERED_ITEM.findall(trimmed))

    signals: list[str] = []
    parts: list[str] = []
    if terms >= VOCABULARY_COMPLEX:
        signals.append("vocabulary")
        parts.append(f"{terms} analysis terms")
    if length >= LENGTH_COMPLEX:
        signals.append("length")
        parts.append(f"{length} chars")
    if counted >= QUESTIONS_COMPLEX:
        signals.append("questions")
        parts.append(f"{counted} questions")
    if signals:
        return _result("complex", signals, parts)

    if (
        length <= LIGHT_MAX_LENGTH
        and questions <= LIGHT_MAX_QUESTIONS
        and _LOOKUP.match(folded) is not None
    ):
        return _result("light", ["lookup"], ["short lookup"])
    return _result("standard", [], ["no signals"])


def _result(tier: str, signals: list[str], parts: list[str]) -> Classification:
    reason = ", ".join(parts)[:REASON_MAX_LENGTH]
    return Classification(tier=tier, reason=reason, signals=tuple(signals))

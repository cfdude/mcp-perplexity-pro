"""Decisions API logic for ``perplexity_decide`` (design D2 to D8).

* Request side (pure, no I/O): ``DecideOptions`` and ``build_request`` validate everything the
  probe showed the API reports vaguely or bills for nothing, then build the ``POST /v1/decisions``
  body.

Everything that can fail on a caller's input raises ``PerplexityError("invalid_request", ...)``
naming ``state``, ``questions`` or the question, so the tool validates first and nothing is sent,
recorded or created for a bad call. The shared validators come from ``agent.py``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from mcp_perplexity_pro.agent import _bad

MODELS = ("pplx-decider-v1.1-27b", "pplx-decider-v1-27b")
DEFAULT_MODEL = MODELS[0]
QUESTION_TYPES = ("noul", "choice", "score")
MAX_QUESTIONS = 32  # our own cap; the API allows 128
MAX_NAME_CHARS = 128  # our own cap
MAX_STATE_CHARS = 200_000  # our own cap on the serialized state; the API's limit is 262144 tokens
MAX_CHOICE_OPTIONS = 255
MAX_SCORE_LEVELS = 10
NOUL_KEYS = ("true", "false")
QUESTION_KEYS = ("type", "criteria", "instructions")


@dataclass(frozen=True)
class DecideOptions:
    """The typed options of ``perplexity_decide``."""

    state: Any
    questions: Any
    model: str = DEFAULT_MODEL


def _has_image(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("data:image/")
    if isinstance(value, dict):
        return "image_url" in value or any(_has_image(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_image(v) for v in value)
    return False


def _state(value: Any) -> Any:
    if isinstance(value, str):
        if not value.strip():
            raise _bad("state", "must not be blank.")
    elif isinstance(value, dict | list):
        if not value:
            raise _bad("state", "must not be empty.")
    else:
        raise _bad("state", "must be text, an object or a list.")
    try:
        size = len(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError, RecursionError):
        raise _bad("state", "must be plain JSON.") from None
    if size > MAX_STATE_CHARS:
        raise _bad("state", f"must be at most {MAX_STATE_CHARS} characters serialized.")
    if _has_image(value):
        raise _bad("state", "images are not supported in this version.")
    return copy.deepcopy(value)


def _instructions(label: str, value: Any) -> None:
    if isinstance(value, str):
        ok = bool(value.strip())
    else:
        ok = isinstance(value, dict | list) and bool(value)
    if not ok:
        raise _bad(label, "instructions must be non-blank text, or a non-empty object or list.")


def _question(name: str, question: Any) -> dict[str, Any]:
    label = f"questions[{name}]"
    if not isinstance(question, dict):
        raise _bad(label, "must be an object with a type.")
    extra = [k for k in question if k not in QUESTION_KEYS]
    if extra:
        raise _bad(label, f"has an unknown key {extra[0]!r}; allowed: {', '.join(QUESTION_KEYS)}.")
    kind = question.get("type")
    if kind not in QUESTION_TYPES:
        raise _bad(label, f"type must be one of {', '.join(QUESTION_TYPES)}.")
    criteria = question.get("criteria")
    instructions = question.get("instructions")
    if instructions is not None:
        _instructions(label, instructions)
    if kind == "noul":
        if criteria is None and instructions is None:
            raise _bad(label, "a noul question needs criteria or instructions.")
        if criteria is not None and (
            not isinstance(criteria, dict)
            or not criteria
            or any(k not in NOUL_KEYS for k in criteria)
        ):
            raise _bad(
                label, "noul criteria must be an object with the keys 'true' and/or 'false'."
            )
    elif kind == "choice":
        if not isinstance(criteria, dict) or not 1 <= len(criteria) <= MAX_CHOICE_OPTIONS:
            raise _bad(
                label,
                f"a choice question needs criteria: an object of 1 to {MAX_CHOICE_OPTIONS} "
                "options.",
            )
    else:
        if not isinstance(criteria, list) or not 1 <= len(criteria) <= MAX_SCORE_LEVELS:
            raise _bad(
                label, f"a score question needs criteria: a list of 1 to {MAX_SCORE_LEVELS} levels."
            )
    return copy.deepcopy(question)


def _questions(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise _bad("questions", "must be a non-empty object of named questions.")
    if len(value) > MAX_QUESTIONS:
        raise _bad(
            "questions", f"at most {MAX_QUESTIONS} questions are allowed (got {len(value)})."
        )
    built: dict[str, Any] = {}
    for name, question in value.items():
        if not isinstance(name, str) or not name.strip():
            raise _bad("questions", "every question name must be non-blank text.")
        if len(name) > MAX_NAME_CHARS:
            raise _bad("questions", f"a question name is at most {MAX_NAME_CHARS} characters.")
        built[name] = _question(name, question)
    return built


def build_request(options: DecideOptions) -> dict[str, Any]:
    """Validate ``options`` and build the ``POST /v1/decisions`` body. Pure: no network, no
    database. ``model`` is always sent. Raises ``invalid_request`` naming the first thing wrong."""
    if options.model not in MODELS:
        raise _bad("model", f"must be one of {', '.join(MODELS)}.")
    return {
        "model": options.model,
        "state": _state(options.state),
        "questions": _questions(options.questions),
    }

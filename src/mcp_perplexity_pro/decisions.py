"""Decisions API logic for ``perplexity_decide`` (design D2 to D8).

* Request side (pure, no I/O): ``DecideOptions`` and ``build_request`` validate everything the
  probe showed the API reports vaguely or bills for nothing, then build the ``POST /v1/decisions``
  body.
* Response side: ``digest`` and the output models.

Everything that can fail on a caller's input raises ``PerplexityError("invalid_request", ...)``
naming ``state``, ``questions`` or the question, so the tool validates first and nothing is sent,
recorded or created for a bad call. The shared validators come from ``agent.py``.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mcp_perplexity_pro import pricing
from mcp_perplexity_pro.agent import _bad
from mcp_perplexity_pro.costed import Costed, Recording, costed_call
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.models import DecisionsResponse
from mcp_perplexity_pro.redaction import scrub_secrets
from mcp_perplexity_pro.usage import Usage, computed_usage, to_tokens

logger = logging.getLogger(__name__)

TOOL = "perplexity_decide"
# The default stays ``pplx-decider-v1.1-27b`` (a different default is a behavior change that needs
# an evaluation, design D3); the other names are accepted and priced by ``pricing``.
MODELS = (
    "pplx-decider-v1.1-27b",
    "pplx-decider-v1-27b",
    "pplx-decider-v1.2",
    "pplx-decider-flash-v1.2",
    "pplx-decider-latest",
    "pplx-decider-flash-latest",
    "perplexity/pplx-decider-latest",
    "perplexity/pplx-decider-flash-latest",
)
DEFAULT_MODEL = "pplx-decider-v1.1-27b"
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
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False))
        if size > MAX_STATE_CHARS:
            raise _bad("state", f"must be at most {MAX_STATE_CHARS} characters serialized.")
        if _has_image(value):
            raise _bad("state", "images are not supported in this version.")
        return copy.deepcopy(value)
    except (TypeError, ValueError, RecursionError):
        raise _bad(
            "state", "must be plain JSON (no NaN or Infinity, not too deeply nested)."
        ) from None


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
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        raise _bad(
            "questions", "must be plain JSON (no NaN or Infinity, not too deeply nested)."
        ) from None
    if size > MAX_STATE_CHARS:
        raise _bad("questions", f"must be at most {MAX_STATE_CHARS} characters serialized.")
    built: dict[str, Any] = {}
    for name, question in value.items():
        if not isinstance(name, str) or not name.strip():
            raise _bad("questions", "every question name must be non-blank text.")
        if len(name) > MAX_NAME_CHARS:
            raise _bad("questions", f"a question name is at most {MAX_NAME_CHARS} characters.")
        try:
            built[name] = _question(name, question)
        except RecursionError:
            raise _bad(f"questions[{name}]", "is nested too deeply.") from None
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


# --- Response side (design D3, D8) -----------------------------------------------------------

TEXT_CAP = 500


class DecisionAnswer(BaseModel):
    type: Annotated[str, Field(description="noul, choice or score")]
    noul: Annotated[float | None, Field(description="noul: probability the answer is yes")] = None
    choice: Annotated[str | None, Field(description="choice: the most probable option")] = None
    confidence: Annotated[
        float | None, Field(description="choice and score: confidence from 0 to 1")
    ] = None
    probabilities: Annotated[
        dict[str, float | None] | None,
        Field(description="choice: option to probability; score: level index to probability"),
    ] = None
    score: Annotated[float | None, Field(description="score: probability-weighted level index")] = (
        None
    )
    legend: Annotated[
        dict[str, str] | None, Field(description="score: level index to its criteria text")
    ] = None


class DecideOutput(BaseModel):
    answers: Annotated[
        dict[str, DecisionAnswer], Field(description="One answer per question, by your names")
    ]
    model: Annotated[str | None, Field(description="The model that answered")] = None
    input_tokens: Annotated[int | None, Field(description="Input tokens billed")] = None
    output_tokens: Annotated[int | None, Field(description="Output tokens (free)")] = None
    cost_usd: Annotated[
        str | None, Field(description="Exact USD cost of the request, as a decimal string")
    ] = None
    cost_source: Annotated[str, Field(description="computed, or none when the cost is unknown")] = (
        "none"
    )
    latency_ms: Annotated[int, Field(description="Measured wall time of the upstream call")] = 0
    project: Annotated[str, Field(description="The project the call was recorded under")] = ""
    warnings: Annotated[list[str], Field(description="Things worth knowing about this result")]


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _text(value: object, secrets: tuple[str, ...]) -> str | None:
    if not isinstance(value, str):
        return None
    return scrub_secrets(value, secrets)[:TEXT_CAP]


def _answer(raw: dict[str, Any], secrets: tuple[str, ...]) -> DecisionAnswer:
    probs = raw.get("probabilities")
    legend = raw.get("legend")
    return DecisionAnswer(
        type=str(raw["type"]),
        noul=_num(raw.get("noul")),
        choice=_text(raw.get("choice"), secrets),
        confidence=_num(raw.get("confidence")),
        probabilities=(
            {(_text(k, secrets) or ""): _num(v) for k, v in probs.items() if isinstance(k, str)}
            if isinstance(probs, dict)
            else None
        ),
        score=_num(raw.get("score")),
        legend=(
            {
                (_text(k, secrets) or ""): (_text(v, secrets) or "")
                for k, v in legend.items()
                if isinstance(k, str) and isinstance(v, str)
            }
            if isinstance(legend, dict)
            else None
        ),
    )


def digest(
    response: DecisionsResponse,
    secrets: Iterable[str] = (),
    *,
    question_names: Iterable[str],
) -> DecideOutput:
    """The tool's result for a response. Total: it never raises (the call is already billed)."""
    secrets = tuple(secrets)
    usage = response.usage if isinstance(response.usage, dict) else {}
    input_tokens = to_tokens(usage.get("input_tokens"))
    output_tokens = to_tokens(usage.get("output_tokens"))
    model = _text(response.model, secrets)
    try:
        answers: dict[str, DecisionAnswer] = {}
        warnings: list[str] = []
        for name in question_names:
            raw = response.answers.get(name)
            if not isinstance(raw, dict) or raw.get("type") not in QUESTION_TYPES:
                warnings.append(f"No readable answer for question {name!r}; it is left out.")
                continue
            answers[name] = _answer(raw, secrets)
        return DecideOutput(
            answers=answers,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            warnings=warnings,
        )
    except Exception:  # total by contract: a malformed body must not hide a billed call
        logger.warning("decisions digest: response could not be read", exc_info=True)
        return DecideOutput(
            answers={},
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            warnings=["The response could not be read."],
        )


# --- Cost and the one costed call (design D4, D5) --------------------------------------------


def decisions_usage(raw: object, model: object) -> Usage:
    """The usage of one decision request: input tokens at the documented price of ``model``, the
    name the request used (output is free, there is no per-request fee), source ``computed``.
    Counts are read with ``usage.to_tokens``; when ``input_tokens`` is not a valid count, or
    ``model`` has no documented price, the cost is unknown (source ``none``), never zero and never
    a default rate. The response's ``usage`` object is kept as ``raw``. Never raises."""
    try:
        mapping = raw if isinstance(raw, Mapping) else {}
        input_tokens = to_tokens(mapping.get("input_tokens"))
        output_tokens = to_tokens(mapping.get("output_tokens"))
        raw_usage = dict(raw) if isinstance(raw, Mapping) else None
        nano = None if input_tokens is None else pricing.decisions_cost_nano(model, input_tokens)
        if nano is None:
            return Usage(input_tokens=input_tokens, output_tokens=output_tokens, raw=raw_usage)
        total = input_tokens + output_tokens if output_tokens is not None else None
        return computed_usage(
            nano,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            input_cost_nano=nano,
            raw=raw_usage,
        )
    except Exception:
        logger.warning("decisions usage: cost could not be computed", exc_info=True)
        return Usage()


async def run_decide(
    app: Any,
    *,
    project: str | None,
    body: dict[str, Any],
    tool: str = TOOL,
    deadline: float | None = None,
) -> Costed[DecisionsResponse]:
    """Send ``body`` and record the request (``costed.costed_call``).

    ``tool`` is the name of the MCP tool whose call caused the request (the event's tool): the
    routing classifier passes the ask or chat tool's name. ``deadline`` is an absolute event-loop
    time (``loop.time()``) by which the request must end (it is made once, with no retry); past
    it the request is cancelled and recorded as ``network_timeout``. A cancel that does not
    come from the deadline is never turned into that error."""

    def interpret(response: DecisionsResponse) -> Recording:
        model = response.model if isinstance(response.model, str) else None
        # priced by the name the request used: a response may echo another name or none
        return Recording(
            status="ok", usage=decisions_usage(response.usage, body.get("model")), model=model
        )

    async def send() -> DecisionsResponse:
        if deadline is None:
            return await app.client.decide(body)
        try:
            async with asyncio.timeout_at(deadline):
                # one attempt: a 429 is reported as rate_limited at once rather than slept on
                # until the deadline cuts it off and mislabels it network_timeout
                return await app.client.decide(body, attempts=1)
        except TimeoutError:
            raise PerplexityError(
                "network_timeout", "The Decisions request did not answer within its time limit."
            ) from None

    return await costed_call(
        app,
        tool=tool,
        api="decisions",
        project=project,
        preset=None,
        call=send,
        record=interpret,
    )

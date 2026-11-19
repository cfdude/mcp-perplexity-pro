"""The model gate and the hints of a call that carries attachments (spec ``media-attachments``).

Pure: no network, no database. ``blocked`` says whether the final route of a call can carry its
input kinds (the model matrix's ``accepts`` and ``preset_accepts``); ``attachment_hint`` words an
upstream refusal of an attachment. The hint for a model the API no longer serves is a SEAM:
``model_gone_hint`` is looked up at call time, its default here is the plain text, and a later
change that knows live same-family models may replace the function.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mcp_perplexity_pro import matrix
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.routing import Route

GENERIC_400 = "invalid request"  # the API's body for several unrelated mistakes
MAX_NAMED_MODELS = 5
# The one description of the parameter on ask and chat: at most 100 characters (spec agent-ask),
# the cost note, nothing about retention.
ATTACHMENTS_DESCRIPTION = (
    "Paths, https URLs or data: URIs of images/documents, at most 10; they add input tokens"
)


def kinds_text(kinds: Iterable[str]) -> str:
    return " and ".join(sorted(kinds))


def _verified_presets() -> str:
    parts = []
    for preset, kinds in matrix.VERIFIED_PRESET_KINDS.items():
        parts.append(f"{preset} ({'/'.join(sorted(kinds))})")
    return ", ".join(parts)


def _accepting_text(kinds: frozenset[str], current: matrix.Matrix) -> str:
    names = sorted(matrix.models_accepting(kinds, current))[:MAX_NAMED_MODELS]
    if not names:
        return f"No model is recorded as accepting {kinds_text(kinds)}."
    return f"Models recorded as accepting {kinds_text(kinds)}: {', '.join(names)}."


def blocked(route: Route, kinds: frozenset[str], current: matrix.Matrix) -> str | None:
    """The refusal text when ``route`` cannot carry ``kinds``, else ``None`` (no kinds is never
    blocked). A model is refused only when the matrix says ``no``; an unknown model is let
    through (the matrix lags the API). A preset is allowed only when ``preset_accepts`` is
    ``yes``."""
    if not kinds:
        return None
    if route.preset is not None:
        if matrix.preset_accepts(route.preset, kinds) == "yes":
            return None
        where = "depth" if route.selected_by == "depth" else f"tier {route.tier}"
        return (
            f"{where}: the preset {route.preset!r} is not verified for {kinds_text(kinds)} "
            f"attachments (verified: {_verified_presets()}). Pass an explicit `model` "
            "(perplexity_models lists the inputs each accepts) or a verified depth."
        )
    model = route.model or ""
    if matrix.accepts(model, kinds, current) != "no":
        return None
    refused = sorted(k for k in kinds if matrix.accepts(model, [k], current) == "no")
    of_tier = f" (the model of tier {route.tier})" if route.selected_by == "tier" else ""
    return (
        f"model: {model!r}{of_tier} does not accept {kinds_text(refused)} attachments (the model "
        f"matrix records a refusal). {_accepting_text(kinds, current)} perplexity_models lists "
        "the inputs of every model."
    )


# --- hints -----------------------------------------------------------------------------------


def _same_with(exc: PerplexityError, message: str) -> PerplexityError:
    return PerplexityError(
        exc.category,
        message,
        status=exc.status,
        api_type=exc.api_type,
        api_code=exc.api_code,
        api_message=exc.api_message,
    )


def _plain_model_gone(exc: PerplexityError, model: str | None) -> PerplexityError:
    named = model or "the requested model"
    return _same_with(
        exc,
        f"model {named} is not served by the API, so nothing about the attachment was wrong. "
        "perplexity_models lists the models that are served.",
    )


model_gone_hint: Any = _plain_model_gone  # the seam: replace to word it differently


def attachment_hint(
    exc: PerplexityError, kinds: frozenset[str], model: str | None = None
) -> PerplexityError:
    """Add the attachment hint to an upstream 400 of a call that carried ``kinds``; any other
    error, and any call with no kinds, is returned untouched. A model the API no longer serves
    gets ``model_gone_hint`` instead (that 400 is about the model, not the attachment)."""
    if not kinds or exc.category != "invalid_request" or exc.status != 400:
        return exc
    body = exc.api_message or str(exc)
    if matrix.model_not_served(400, body, model):
        return model_gone_hint(exc, model)
    sent = kinds_text(kinds)
    if exc.api_message == GENERIC_400:
        return _same_with(
            exc,
            f"{exc} The model may not accept {sent} attachments: perplexity_models lists the "
            "inputs each model accepts.",
        )
    return _same_with(exc, f"{exc} The call carried {sent} attachments.")


def refusal_hint(kinds: frozenset[str]) -> str:
    """The sentence added to a run that failed with a ``refusal`` error on a call with a
    document."""
    return (
        f" The model refused the {kinds_text(kinds)} attachment; another model may read it "
        "(perplexity_models lists the inputs each accepts)."
    )

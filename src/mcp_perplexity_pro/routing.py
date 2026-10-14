"""Which model answers a call: the routing mode, the three selectors and the text that tells
the calling agent (routing-modes-config).

Pure: no network, no database. The configured mode only supplies what a call does not choose
itself; an explicit ``model`` is always used as given.
"""

from __future__ import annotations

from dataclasses import dataclass

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.settings import TIER_NAMES, Settings

ASK_DEPTHS = ("fast", "low", "medium")
LONG_DEPTHS = ("high", "xhigh")


@dataclass(frozen=True)
class Route:
    """What one call resolved to. ``selected_by`` is ``default``, ``tier``, ``depth`` or
    ``model``: the rule that applied. A preset route has ``preset`` and no ``model``."""

    mode: str
    tier: str | None
    model: str | None
    preset: str | None
    selected_by: str


def _bad(option: str, message: str) -> PerplexityError:
    return PerplexityError("invalid_request", f"{option}: {message}")


def _default_description(settings: Settings) -> str:
    if settings.routing == "custom":
        return f"the standard tier ({settings.tier_standard})"
    return settings.model


def resolve(
    settings: Settings,
    *,
    depth: str | None = None,
    tier: str | None = None,
    model: str | None = None,
) -> Route:
    """Resolve one call. Refusals come in a fixed order: a conflict between selectors, then
    ``tier`` outside ``custom``, then an unknown ``tier``, then a depth that is not allowed."""
    given = [
        name
        for name, value in (("depth", depth), ("tier", tier), ("model", model))
        if value is not None
    ]
    if len(given) > 1:
        named = " and ".join(f"`{n}`" for n in given)
        raise _bad(
            " and ".join(given),
            f"{named} cannot be combined: each one selects the model on its own. Pass one of "
            f"them, or neither to use this server's default ({_default_description(settings)}).",
        )
    if tier is not None:
        if settings.routing != "custom":
            raise _bad(
                "tier",
                f"only works when the server runs in custom routing mode; this one runs in "
                f"{settings.routing} mode. Omit `tier` (the default is "
                f"{_default_description(settings)}), or pass `depth` or `model`.",
            )
        if tier not in TIER_NAMES:
            raise _bad("tier", f"must be one of {', '.join(TIER_NAMES)}.")
        return Route("custom", tier, getattr(settings, f"tier_{tier}"), None, "tier")
    if depth is not None:
        if depth in LONG_DEPTHS:
            raise _bad(
                "depth", f"{depth!r} can last minutes and cost dollars: use perplexity_research."
            )
        if depth not in ASK_DEPTHS:
            raise _bad("depth", f"must be one of {', '.join(ASK_DEPTHS)}.")
        return Route(settings.routing, None, None, depth, "depth")
    if model is not None:
        return Route(settings.routing, None, model, None, "model")
    if settings.routing == "custom":
        return Route("custom", "standard", settings.tier_standard, None, "default")
    return Route(settings.routing, None, settings.model, None, "default")


def description_sentence(settings: Settings) -> str:
    """One paragraph for the ask and chat tool descriptions: the mode, what a call with no
    selector uses, and that the default's cost differs from the per-depth figures."""
    if settings.routing == "custom":
        head = (
            "Routing mode: custom. With no depth, tier or model the standard tier "
            f"({settings.tier_standard}) answers; `tier` picks light ({settings.tier_light}), "
            f"standard or complex ({settings.tier_complex})."
        )
    else:
        head = (
            f"Routing mode: standard. With no depth, tier or model {settings.model} answers "
            "with web search; `tier` is for custom mode only."
        )
    return (
        f"{head} A `model` is always used as given. The per-depth costs above apply to depth; "
        "the default model's cost differs (see perplexity_usage)."
    )


def instructions_text(settings: Settings) -> str:
    """The MCP ``instructions``: a pure function of the settings, with no secret in it."""
    if settings.routing == "custom":
        picking = (
            "Routing mode: custom. Three models are configured: "
            f"light = {settings.tier_light} (light or agent-execution work), "
            f"standard = {settings.tier_standard} (everyday work, the default), "
            f"complex = {settings.tier_complex} (work needing deeper reasoning). "
            "Pass `tier` (light, standard or complex) on perplexity_ask or perplexity_chat to "
            "pick one."
        )
    else:
        picking = (
            f"Routing mode: standard. Calls that name nothing use {settings.model} with web search."
        )
    return (
        f"{picking} Pass `depth` (fast, low or medium) to use a Perplexity preset instead, or "
        "`model` to name any model id; an explicit model is always used exactly as given. "
        "Pass only one of `tier`, `depth` and `model` per call. Override the default only "
        "when the user asks. Depths high and xhigh belong to perplexity_research."
    )

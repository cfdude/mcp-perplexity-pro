"""Which model answers a call: the routing mode, the three selectors and the text that tells
the calling agent (routing-modes-config).

Pure: no network, no database. The configured mode only supplies what a call does not choose
itself; an explicit ``model`` is always used as given.
"""

from __future__ import annotations

from dataclasses import dataclass

from mcp_perplexity_pro import rules
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.settings import TIER_NAMES, Settings

ASK_DEPTHS = ("fast", "low", "medium")
LONG_DEPTHS = ("high", "xhigh")
# The preset a dynamic tier runs when no ``PERPLEXITY_TIER_*`` variable replaces it. ``standard``
# runs a model, and ``high`` and ``xhigh`` are in no row, so dynamic mode cannot select them.
DYNAMIC_PRESETS = {"light": "fast", "complex": "medium"}
REASON_MAX_LENGTH = 120


@dataclass(frozen=True)
class Route:
    """What one call resolved to. ``selected_by`` is ``default``, ``tier``, ``depth``, ``model``
    or ``classifier``: the rule that applied. A preset route has ``preset`` and no ``model``.
    ``reason`` and ``classifier`` are set only when dynamic mode classified the call (or said
    search is off, which has a reason and no classifier)."""

    mode: str
    tier: str | None
    model: str | None
    preset: str | None
    selected_by: str
    reason: str | None = None
    classifier: str | None = None


def _bad(option: str, message: str) -> PerplexityError:
    return PerplexityError("invalid_request", f"{option}: {message}")


def _default_description(settings: Settings) -> str:
    if settings.routing == "custom":
        return f"the standard tier ({settings.tier_standard})"
    if settings.routing == "dynamic":
        return "the tier picked from the prompt"
    return settings.model


def dynamic_route(
    settings: Settings,
    tier: str,
    *,
    selected_by: str = "classifier",
    reason: str | None = None,
    classifier: str | None = None,
) -> Route:
    """The route of a dynamic tier: a ``PERPLEXITY_TIER_*`` model when set, else the tier's
    default (light is preset ``fast``, standard is ``PERPLEXITY_MODEL``, complex is ``medium``)."""
    model = getattr(settings, f"tier_{tier}")
    if model is None and tier == "standard":
        model = settings.model
    preset = None if model is not None else DYNAMIC_PRESETS[tier]
    return Route("dynamic", tier, model, preset, selected_by, reason, classifier)


def tier_of(settings: Settings, preset: str | None, model: str | None) -> str:
    """The dynamic tier a stored turn ran, from its stored ``preset`` and ``model``.

    A stored preset decides alone (the stored model of a preset run is the one the API reports,
    which no tier names); otherwise the stored model is matched against the tiers' models. A tie
    takes the highest tier and no match is ``standard``. A tier replaced by a
    ``PERPLEXITY_TIER_*`` model has no preset, so it matches by model only.
    """
    routes = {tier: dynamic_route(settings, tier) for tier in TIER_NAMES}
    if preset is not None:
        matches = [t for t in TIER_NAMES if routes[t].preset == preset]
    elif model is not None:
        matches = [t for t in TIER_NAMES if routes[t].model == model]
    else:
        matches = []
    return matches[-1] if matches else "standard"


def _cap(reason: str) -> str:
    """At most 120 ASCII characters, so a reason stays short and safe to log."""
    return reason.encode("ascii", "replace").decode("ascii")[:REASON_MAX_LENGTH]


def _classified(
    settings: Settings,
    text: str | None,
    previous: str | None,
    search: bool | None,
    classification: rules.Classification | None,
) -> Route:
    """Dynamic mode with no selector named."""
    if search is False:  # a preset always searches, so the model route; no floor, no rules
        return dynamic_route(settings, "standard", selected_by="default", reason="search off")
    if classification is None:
        if text is None:
            return dynamic_route(settings, "standard", selected_by="default")
        classification = rules.classify(text)
    tier, reason = classification.tier, classification.reason
    if previous in TIER_NAMES and TIER_NAMES.index(previous) > TIER_NAMES.index(tier):
        tier, reason = previous, f"{reason}, held at {previous}"
    return dynamic_route(settings, tier, reason=_cap(reason), classifier=classification.classifier)


def resolve(
    settings: Settings,
    *,
    depth: str | None = None,
    tier: str | None = None,
    model: str | None = None,
    text: str | None = None,
    previous: str | None = None,
    search: bool | None = None,
    classification: rules.Classification | None = None,
) -> Route:
    """Resolve one call. Refusals come in a fixed order: a conflict between selectors, then
    ``tier`` outside ``custom`` and ``dynamic``, then an unknown ``tier``, then a depth that is
    not allowed.

    ``text``, ``previous`` (the tier a chat last ran), ``search`` and ``classification`` (a
    ready verdict from another classifier) matter only in ``dynamic`` mode with no selector
    named: the call is classified (the rules over ``text``, unless ``classification`` is given),
    held at ``previous`` when that is higher, and run on the standard tier's model when
    ``search`` is false."""
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
            f"them, or neither"
            + (
                " (with neither, the tier is picked from the prompt)."
                if settings.routing == "dynamic"
                else f" to use this server's default ({_default_description(settings)})."
            ),
        )
    if tier is not None:
        if settings.routing not in ("custom", "dynamic"):
            raise _bad(
                "tier",
                f"only works when the server runs in custom or dynamic routing mode; this one "
                f"runs in {settings.routing} mode. Omit `tier` (the default is "
                f"{_default_description(settings)}), or pass `depth` or `model`.",
            )
        if tier not in TIER_NAMES:
            raise _bad("tier", f"must be one of {', '.join(TIER_NAMES)}.")
        if settings.routing == "dynamic":
            route = dynamic_route(settings, tier, selected_by="tier")
            if search is False and route.preset is not None:
                raise _bad(
                    "tier and search",
                    f"`tier` {tier} runs preset {route.preset} and a preset always searches, so "
                    "it cannot be combined with `search` false. Pass `model`, tier standard or "
                    "search true.",
                )
            return route
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
    if settings.routing == "dynamic":
        return _classified(settings, text, previous, search, classification)
    return Route(settings.routing, None, settings.model, None, "default")


def describe_tiers(settings: Settings) -> str:
    """The three dynamic tiers as one line for the startup log (no secret in it)."""
    parts = []
    for tier in TIER_NAMES:
        route = dynamic_route(settings, tier)
        what = f"preset {route.preset}" if route.preset else f"model {route.model}"
        parts.append(f"{tier}={what}")
    return ", ".join(parts)


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
    selectors = (
        "`tier`, `depth` and `model`" if settings.routing == "custom" else "`depth` and `model`"
    )
    return (
        f"{picking} Pass `depth` (fast, low or medium) to use a Perplexity preset instead, or "
        "`model` to name any model id; an explicit model is always used exactly as given. "
        f"Pass only one of {selectors} per call. Override the default only "
        "when the user asks. Depths high and xhigh belong to perplexity_research. "
        "Call perplexity_help for how to use the tools."
    )

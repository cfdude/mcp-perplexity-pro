"""``perplexity_models``: the live model list with prices, plus the documented preset table."""

from typing import Annotated

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_perplexity_pro.catalog import PRESETS, CatalogModel, Listing, PresetSection
from mcp_perplexity_pro.rules import CLASSIFIER
from mcp_perplexity_pro.settings import TIER_NAMES, Settings, dynamic_target


class ConfiguredModel(BaseModel):
    name: Annotated[str, Field(description="model, or the tier: light, standard, complex")]
    id: Annotated[str | None, Field(description="The configured model id; null for a preset")]
    preset: Annotated[str | None, Field(description="The preset a dynamic tier runs")] = None
    known: Annotated[
        bool | None,
        Field(description="Whether the live list has it; still used if not; null for a preset"),
    ]


class RoutingSection(BaseModel):
    mode: Annotated[str, Field(description="standard, custom or dynamic")]
    models: Annotated[list[ConfiguredModel], Field(description="The configured model or tiers")]
    classifier: Annotated[
        str | None, Field(description="Dynamic mode: who picks the tier (rules)")
    ] = None


class ModelsResult(BaseModel):
    models: Annotated[
        list[CatalogModel], Field(description="Live models (after the provider filter)")
    ]
    providers: Annotated[
        list[str], Field(description="Every provider in the live list, ignoring the filter")
    ]
    stale: Annotated[
        bool, Field(description="True when the live request failed and a cached list is shown")
    ]
    age_seconds: Annotated[float, Field(description="Seconds since the list was fetched live")]
    presets: Annotated[
        PresetSection, Field(description="Documented Agent API presets; not live data")
    ]
    routing: Annotated[
        RoutingSection, Field(description="Active routing; configuration, not live data")
    ]


def _price(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def render(result: ModelsResult, provider: str | None) -> str:
    """A plain-text rendering of ``result`` for clients that show only text."""
    lines = []
    if result.stale:
        lines.append(
            f"STALE: the live request failed; showing the list fetched "
            f"{result.age_seconds:.0f}s ago."
        )
    scope = f" for provider {provider!r}" if provider else ""
    lines.append(
        f"{len(result.models)} live models{scope} (providers: {', '.join(result.providers)})"
    )
    if not result.models and provider:
        lines.append(f"No model matches provider {provider!r}; real providers are listed above.")
    if result.models:
        lines.append("id | provider | input | output | cache_read | cache_write | unit")
    for m in result.models:
        p = m.pricing
        lines.append(
            f"{m.id} | {m.provider or '-'} | {_price(p.input)} | {_price(p.output)} | "
            f"{_price(p.cache_read)} | {_price(p.cache_write)} | {p.unit or '-'}"
        )
    lines.append("")
    configured = ", ".join(
        f"{m.name} = preset {m.preset}"
        if m.preset
        else f"{m.name} = {m.id}{'' if m.known else ' (not in the live list)'}"
        for m in result.routing.models
    )
    classifier = f" (classifier {result.routing.classifier})" if result.routing.classifier else ""
    lines.append(f"Routing mode {result.routing.mode}{classifier}: {configured}")
    section = result.presets
    lines.append("")
    lines.append(f"Agent API presets (source: {section.source}, as of {section.as_of}):")
    lines.extend(f"  {p.name} -> {p.model}" for p in section.presets)
    lines.append(section.note)
    return "\n".join(lines)


def routing_section(listing: Listing, settings: Settings) -> RoutingSection:
    live = {m.id for m in listing.for_provider(None)}
    if settings.routing == "dynamic":
        models = []
        for tier in TIER_NAMES:
            model, preset = dynamic_target(settings, tier)
            if preset is not None:
                models.append(ConfiguredModel(name=tier, id=None, preset=preset, known=None))
            else:
                models.append(ConfiguredModel(name=tier, id=model, known=model in live))
        return RoutingSection(mode="dynamic", models=models, classifier=CLASSIFIER)
    if settings.routing == "custom":
        wanted = [(t, getattr(settings, f"tier_{t}")) for t in TIER_NAMES]
    else:
        wanted = [("model", settings.model)]
    return RoutingSection(
        mode=settings.routing,
        models=[ConfiguredModel(name=n, id=i, known=i in live) for n, i in wanted],
    )


def build_result(listing: Listing, provider: str | None, settings: Settings) -> ModelsResult:
    return ModelsResult(
        models=listing.for_provider(provider),
        providers=listing.providers,
        stale=listing.stale,
        age_seconds=round(listing.age_seconds, 3),
        presets=PRESETS,
        routing=routing_section(listing, settings),
    )


def register(server: FastMCP) -> None:
    @server.tool(
        name="perplexity_models",
        output_schema=ModelsResult.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    )
    async def perplexity_models(
        ctx: Context,
        provider: Annotated[
            str | None,
            Field(description="Only models from this provider (case-insensitive), e.g. anthropic"),
        ] = None,
        refresh: Annotated[
            bool, Field(description="Bypass the cache and fetch the list now")
        ] = False,
    ) -> ToolResult:
        """List the models available to the configured key with their prices (live data), plus
        the documented Agent API presets as a separate section."""
        listing = await ctx.lifespan_context.catalog.get(refresh=refresh)
        result = build_result(listing, provider, ctx.lifespan_context.settings)
        return ToolResult(
            content=render(result, provider),
            structured_content=result.model_dump(mode="json"),
        )

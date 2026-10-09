"""``perplexity_models``: the live model list with prices, plus the documented preset table."""

from typing import Annotated

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_perplexity_pro.catalog import PRESETS, CatalogModel, Listing, PresetSection


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
    section = result.presets
    lines.append("")
    lines.append(f"Agent API presets (source: {section.source}, as of {section.as_of}):")
    lines.extend(f"  {p.name} -> {p.model}" for p in section.presets)
    lines.append(section.note)
    return "\n".join(lines)


def build_result(listing: Listing, provider: str | None) -> ModelsResult:
    return ModelsResult(
        models=listing.for_provider(provider),
        providers=listing.providers,
        stale=listing.stale,
        age_seconds=round(listing.age_seconds, 3),
        presets=PRESETS,
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
        result = build_result(listing, provider)
        return ToolResult(
            content=render(result, provider),
            structured_content=result.model_dump(mode="json"),
        )

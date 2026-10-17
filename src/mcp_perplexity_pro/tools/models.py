"""``perplexity_models``: the live model list with prices, plus the documented preset table."""

from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_perplexity_pro import matrix as model_matrix
from mcp_perplexity_pro.catalog import PRESETS, CatalogModel, Listing, PresetSection
from mcp_perplexity_pro.decisions import DEFAULT_MODEL as DEFAULT_DECIDER
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
        str | None, Field(description="Dynamic mode: who picks the tier (rules or decisions)")
    ] = None
    decider_model: Annotated[
        str | None, Field(description="Decisions classifier: the decider model asked")
    ] = None


class Efforts(BaseModel):
    accepted: Annotated[
        list[str], Field(description="reasoning.effort levels the model took (empty if unprobed)")
    ]
    refused: Annotated[list[str], Field(description="Levels it refused with a 400")]
    source: Annotated[
        Literal["probe", "baseline", "unprobed"],
        Field(description="How learned; unprobed means unknown"),
    ]


class ListedModel(CatalogModel):
    efforts: Annotated[
        Efforts | None,
        Field(
            description="Effort levels from the matrix; absent for a model it lacks",
            exclude_if=lambda value: value is None,
        ),
    ] = None


class MatrixSection(BaseModel):
    origin: Annotated[Literal["file", "baseline"], Field(description="Stored file or baseline")]
    fetched_at: Annotated[str, Field(description="When the matrix last read the live list (UTC)")]
    unprobed: Annotated[int, Field(description="Available matrix models with efforts unknown")]


class ModelsResult(BaseModel):
    models: Annotated[
        list[ListedModel], Field(description="Live models (after the provider filter)")
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
    matrix: Annotated[MatrixSection, Field(description="Where the efforts come from")]


def _price(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def _efforts_text(efforts: Efforts | None) -> str:
    """``-`` when unknown, ``all`` when every level is taken, else the accepted levels and, when
    any were refused, which."""
    if efforts is None or efforts.source == "unprobed":
        return "-"
    if len(efforts.accepted) == len(model_matrix.LEVELS):
        return "all"
    accepted = ",".join(efforts.accepted) or "none"
    return f"{accepted} (refused {','.join(efforts.refused)})" if efforts.refused else accepted


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
        lines.append("id | provider | input | output | cache_read | cache_write | unit | efforts")
    for m in result.models:
        p = m.pricing
        lines.append(
            f"{m.id} | {m.provider or '-'} | {_price(p.input)} | {_price(p.output)} | "
            f"{_price(p.cache_read)} | {_price(p.cache_write)} | {p.unit or '-'} | "
            f"{_efforts_text(m.efforts)}"
        )
    lines.append("")
    section_matrix = result.matrix
    lines.append(
        f"Matrix: {section_matrix.origin}, fetched {section_matrix.fetched_at}, "
        f"{section_matrix.unprobed} unprobed"
    )
    configured = ", ".join(
        f"{m.name} = preset {m.preset}"
        if m.preset
        else f"{m.name} = {m.id}{'' if m.known else ' (not in the live list)'}"
        for m in result.routing.models
    )
    classifier = f" (classifier {result.routing.classifier})" if result.routing.classifier else ""
    if result.routing.decider_model:
        classifier = (
            f" (classifier {result.routing.classifier}, decider {result.routing.decider_model})"
        )
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
        return RoutingSection(
            mode="dynamic",
            models=models,
            classifier=settings.classifier,
            decider_model=DEFAULT_DECIDER if settings.classifier == "decisions" else None,
        )
    if settings.routing == "custom":
        wanted = [(t, getattr(settings, f"tier_{t}")) for t in TIER_NAMES]
    else:
        wanted = [("model", settings.model)]
    return RoutingSection(
        mode=settings.routing,
        models=[ConfiguredModel(name=n, id=i, known=i in live) for n, i in wanted],
    )


def listed_model(model: CatalogModel, rows: model_matrix.Matrix) -> ListedModel:
    """A live model with its efforts joined by id; none when the matrix lacks it or holds it
    ``removed`` (a removed row is history, not a fact about a model the API lists)."""
    row = rows.models.get(model.id)
    efforts = None
    if row is not None and row.status == "available":
        efforts = Efforts(
            accepted=list(row.efforts.accepted),
            refused=[lv for lv in model_matrix.LEVELS if lv in row.efforts.refused],
            source=row.efforts.source,
        )
    return ListedModel(**model.model_dump(), efforts=efforts)


def matrix_section(snapshot: model_matrix.Loaded) -> MatrixSection:
    rows = snapshot.matrix.models.values()
    return MatrixSection(
        origin=snapshot.origin,
        fetched_at=snapshot.matrix.fetched_at,
        unprobed=sum(1 for r in rows if r.status == "available" and r.efforts.source == "unprobed"),
    )


def build_result(
    listing: Listing, provider: str | None, settings: Settings, snapshot: model_matrix.Loaded
) -> ModelsResult:
    return ModelsResult(
        models=[listed_model(m, snapshot.matrix) for m in listing.for_provider(provider)],
        providers=listing.providers,
        stale=listing.stale,
        age_seconds=round(listing.age_seconds, 3),
        presets=PRESETS,
        routing=routing_section(listing, settings),
        matrix=matrix_section(snapshot),
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
        """List the models available to the configured key with their prices (live data) and the
        effort levels each accepts (from the matrix), plus the documented Agent API presets as a
        separate section."""
        app = ctx.lifespan_context
        listing = await app.catalog.get(refresh=refresh)
        # the stored matrix: ``refresh`` refreshes the catalog list only, never the matrix
        result = build_result(listing, provider, app.settings, app.matrix.snapshot())
        return ToolResult(
            content=render(result, provider),
            structured_content=result.model_dump(mode="json"),
        )

"""``perplexity_ask``: a stateless, synchronous, web-grounded answer (agent-ask spec)."""

import inspect
from dataclasses import replace
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_perplexity_pro.agent import (
    AskOptions,
    Digest,
    Source,
    UsageSummary,
    build_request,
    check_text,
    digest,
    run_costed,
    source_line,
)
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.help_text import POINTER
from mcp_perplexity_pro.routing import Route, description_sentence, resolve
from mcp_perplexity_pro.routing_decisions import classify_dynamic, wants_decider
from mcp_perplexity_pro.settings import Settings
from mcp_perplexity_pro.storage.projects import DEFAULT_PROJECT, validate_project_name

TOOL = "perplexity_ask"
GENERIC_400 = "invalid request"  # the API's body for several unrelated mistakes (design D6)


class Routing(BaseModel):
    """How the model was picked for one call."""

    mode: Annotated[str, Field(description="Server routing mode")]
    tier: Annotated[str | None, Field(description="Tier used, if any")] = None
    model: Annotated[str | None, Field(description="Model id requested; null for a preset")] = None
    selected_by: Annotated[str, Field(description="default, tier, depth, model or classifier")]
    classifier: Annotated[
        str | None, Field(description="Who picked the tier: rules or decisions")
    ] = None
    reason: Annotated[str | None, Field(description="Why dynamic mode routed it so")] = None

    @classmethod
    def of(cls, route: Route) -> "Routing":
        return cls(
            mode=route.mode,
            tier=route.tier,
            model=route.model,
            selected_by=route.selected_by,
            classifier=route.classifier,
            reason=route.reason,
        )


class AskResult(BaseModel):
    """The result of one answered call; ``perplexity_chat`` send extends it (design D10)."""

    answer: Annotated[str, Field(description="The answer text; markers such as [1] are unchanged")]
    answer_json: Annotated[
        Any,
        Field(description="The parsed answer when json_schema was given and it parsed, else null"),
    ] = None
    sources: Annotated[
        list[Source],
        Field(description="Pages the run found or fetched (not necessarily cited), by first use"),
    ]
    status: Annotated[str, Field(description="completed or incomplete")]
    incomplete_reason: Annotated[
        str | None, Field(description="Why an incomplete run stopped, e.g. max_output_tokens")
    ] = None
    warnings: Annotated[list[str], Field(description="Things worth knowing about this result")]
    model: Annotated[str | None, Field(description="The model that answered")] = None
    depth: Annotated[str | None, Field(description="The preset used; null with an explicit model")]
    response_id: Annotated[str | None, Field(description="The API's response id")] = None
    usage: Annotated[UsageSummary, Field(description="Tokens and cost of this call")]
    latency_ms: Annotated[int, Field(description="Measured wall time of the upstream call")]
    project: Annotated[str, Field(description="The project the call was recorded under")]
    routing: Annotated[Routing | None, Field(description="How the model was picked")] = None


def build_result(d: Digest, *, route: Route, latency_ms: int, project: str) -> AskResult:
    return AskResult(
        answer=d.answer,
        answer_json=d.answer_json,
        sources=d.sources,
        status=d.status,
        incomplete_reason=d.incomplete_reason,
        warnings=d.warnings,
        model=d.model,
        depth=route.preset,
        response_id=d.response_id,
        usage=d.usage,
        latency_ms=latency_ms,
        project=project,
        routing=Routing.of(route),
    )


def render_answer(result: AskResult) -> str:
    """The readable text: the answer, a numbered source list and one usage line."""
    lines = [result.answer or "(the run produced no answer text)"]
    lines.extend(f"Warning: {w}" for w in result.warnings)
    if result.sources:
        lines.append("")
        lines.append("Sources:")
        lines.extend(source_line(i, s) for i, s in enumerate(result.sources, 1))
    lines.append("")
    lines.append(render_usage(result))
    return "\n".join(lines)


def render_usage(result: AskResult) -> str:
    u = result.usage
    cost = f"cost {u.cost_usd} USD ({u.cost_source})" if u.cost_usd is not None else "cost unknown"
    tokens = f", {u.total_tokens} tokens" if u.total_tokens is not None else ""
    model = f"{result.model}, " if result.model else ""
    return f"Usage: {model}{cost}{tokens}, {result.latency_ms} ms, project {result.project}."


def schema_hint(exc: PerplexityError) -> PerplexityError:
    """The API answers an invalid inner JSON schema with the same generic 400 it gives for other
    mistakes, so the hint is worded as a likely cause, and only for that exact body."""
    if exc.category == "invalid_request" and exc.status == 400 and exc.api_message == GENERIC_400:
        return PerplexityError(
            "invalid_request",
            f"{exc} Most likely the json_schema is invalid: the API gives this generic error for "
            "a schema it cannot use (check every nested type and property).",
            status=exc.status,
            api_type=exc.api_type,
            api_code=exc.api_code,
            api_message=exc.api_message,
        )
    return exc


def register(server: FastMCP, settings: Settings) -> None:
    async def perplexity_ask(
        ctx: Context,
        query: Annotated[str, Field(description="The question (at most 20000 characters)")],
        project: Annotated[
            str | None,
            Field(description="Project to record the call under (default: default)"),
        ] = None,
        depth: Annotated[
            str | None,
            Field(
                description="fast, low or medium; selects a search preset. high and xhigh are "
                "refused: use perplexity_research. Cannot be combined with tier or model"
            ),
        ] = None,
        model: Annotated[
            str | None,
            Field(
                description="An explicit model id, e.g. openai/gpt-6-luna, instead of a depth. "
                "It searches with the web search tool and 3 steps unless search is false"
            ),
        ] = None,
        tier: Annotated[
            str | None,
            Field(
                description="light, standard or complex: custom or dynamic mode only. "
                "Cannot be combined with depth or model"
            ),
        ] = None,
        search: Annotated[
            bool | None,
            Field(
                description="false answers from the model alone (not with depth: a depth "
                "always searches). true is accepted and changes nothing"
            ),
        ] = None,
        domains: Annotated[
            list[str] | None,
            Field(
                description="At most 20 domains to search: all allowed (python.org) or all "
                "denied with a '-' prefix (-reddit.com); not mixed"
            ),
        ] = None,
        recency: Annotated[str | None, Field(description="hour, day, week, month or year")] = None,
        after: Annotated[
            str | None, Field(description="Only results published after this date (YYYY-MM-DD)")
        ] = None,
        before: Annotated[
            str | None, Field(description="Only results published before this date (YYYY-MM-DD)")
        ] = None,
        country: Annotated[
            str | None, Field(description="Two-letter country code to localize the search, e.g. US")
        ] = None,
        max_results: Annotated[
            int | None, Field(description="Search results to retrieve, 1 to 50")
        ] = None,
        instructions: Annotated[
            str | None,
            Field(description="System-style instructions, at most 10000 characters"),
        ] = None,
        max_output_tokens: Annotated[
            int | None, Field(description="Cap on answer tokens, 1 to 64000")
        ] = None,
        json_schema: Annotated[
            dict[str, Any] | None,
            Field(description="A JSON Schema (root type object) for a structured answer"),
        ] = None,
    ) -> ToolResult:
        """Ask one web-grounded question and get the answer with its sources. Synchronous and
        stateless; it never waits for a background run (use perplexity_research for those).

        Approximate cost per call by depth (observed ranges; the upper figures are estimates):
        fast $0.001 to $0.002, low $0.0005 to $0.004 (up to about $0.02
        estimated), medium $0.016 to $0.025 as a research run (up to about $0.05 estimated; a
        synchronous medium call was not measured). high and xhigh can cost dollars and take
        minutes (unmeasured estimates), so they exist only behind perplexity_research. Giving a
        search filter (domains, recency, after, before, country, max_results) makes the run use
        the web search tool alone, so a filtered medium run loses the preset's page fetching.

        The request sets store to false, which only hides the response from retrieval; the
        provider's documentation says it still persists state, so this is not a retention
        control. Sources are what the run touched, not a citation of each claim. Every call that
        reaches the API is recorded as spend (see perplexity_usage)."""
        check_text("query", query)
        app = ctx.lifespan_context
        decider = wants_decider(app.settings, depth=depth, tier=tier, model=model, search=search)
        # With the Decisions classifier the route below is provisional (the standard tier's
        # model: enough to validate every option); the real one is resolved after validation.
        options = AskOptions(
            route=resolve(
                app.settings,
                depth=depth,
                tier=tier,
                model=model,
                text=None if decider else query,
                search=search,
            ),
            search=search,
            domains=domains,
            recency=recency,
            after=after,
            before=before,
            country=country,
            max_results=max_results,
            instructions=instructions,
            max_output_tokens=max_output_tokens,
            json_schema=json_schema,
        )
        request = build_request(options, query, store=False)
        if decider:  # only now: an invalid call spends nothing (the project name is checked first)
            name = validate_project_name(project or DEFAULT_PROJECT)
            classification = await classify_dynamic(app, query, project=name, tool=TOOL)
            options = replace(
                options,
                route=resolve(
                    app.settings, text=query, search=search, classification=classification
                ),
            )
            request = build_request(options, query, store=False)
        try:
            costed = await run_costed(
                app,
                tool=TOOL,
                project=project,
                body=request,
                preset=options.preset,
                background=False,
            )
        except PerplexityError as exc:
            raise (schema_hint(exc) if json_schema is not None else exc) from None
        result = build_result(
            digest(
                costed.run,
                structured=json_schema is not None,
                secrets=(app.settings.api_key.get_secret_value(),),
            ),
            route=options.route,
            latency_ms=costed.latency_ms,
            project=costed.project,
        )
        return ToolResult(
            content=render_answer(result), structured_content=result.model_dump(mode="json")
        )

    server.tool(
        name=TOOL,
        description=f"{inspect.cleandoc(perplexity_ask.__doc__)}\n\n{description_sentence(settings)}{POINTER}",
        output_schema=AskResult.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
    )(perplexity_ask)

"""``perplexity_decide``: calibrated answers to typed questions about a text (decisions-tool)."""

from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_perplexity_pro.costed import cost_fields
from mcp_perplexity_pro.decisions import (
    DEFAULT_MODEL,
    TOOL,
    DecideOptions,
    DecideOutput,
    build_request,
    digest,
    run_decide,
)


def render_answers(result: DecideOutput) -> str:
    """The readable text: warnings, one line per question and one usage line."""
    lines = [f"Warning: {w}" for w in result.warnings]
    for name, a in result.answers.items():
        if a.type == "noul":
            body = f"noul {a.noul}"
        elif a.type == "choice":
            body = f"choice {a.choice} (confidence {a.confidence}, probabilities {a.probabilities})"
        else:
            body = f"score {a.score} (confidence {a.confidence}, probabilities {a.probabilities})"
        lines.append(f"{name}: {body}")
    if not result.answers:
        lines.append("No answers.")
    cost = (
        f"cost {result.cost_usd} USD ({result.cost_source})" if result.cost_usd else "cost unknown"
    )
    tokens = (
        f"{result.input_tokens} input tokens"
        if result.input_tokens is not None
        else "tokens unknown"
    )
    lines.append("")
    lines.append(
        f"Usage: {result.model}, {tokens}, {cost}, {result.latency_ms} ms, "
        f"project {result.project}."
    )
    return "\n".join(lines)


def register(server: FastMCP) -> None:
    @server.tool(
        name=TOOL,
        output_schema=DecideOutput.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
    )
    async def perplexity_decide(
        ctx: Context,
        state: Annotated[
            Any,
            Field(
                description="What to judge: non-blank text, or a non-empty JSON object or list. "
                "Images are not supported"
            ),
        ],
        questions: Annotated[
            dict[str, Any],
            Field(
                description="1 to 32 questions by a name you choose. Each is {type, criteria, "
                "instructions}: noul (yes/no: criteria {true, false} or instructions), choice "
                "(criteria: object of 1 to 255 options) or score (criteria: list of 1 to 10 levels)"
            ),
        ],
        project: Annotated[
            str | None,
            Field(description="Project to record the call under (default: default)"),
        ] = None,
        model: Annotated[
            str,
            Field(description="pplx-decider-v1.1-27b (default) or pplx-decider-v1-27b"),
        ] = DEFAULT_MODEL,
    ) -> ToolResult:
        """Put typed questions about a text to the Decisions API and get a calibrated answer
        for each: a yes probability (noul), the most probable option with every option's
        probability (choice), or a probability-weighted position on an ordered rubric (score).
        The answers are model probabilities, not facts: you choose the threshold. Costs about
        $0.02 per million input tokens (output is free), a few thousandths of a cent per call,
        however many questions one call holds; a refused call costs nothing. Every request that
        reaches the API is recorded as spend (see perplexity_usage)."""
        options = DecideOptions(state=state, questions=questions, model=model)
        request = build_request(options)
        app = ctx.lifespan_context
        costed = await run_decide(app, project=project, body=request)
        cost_usd, cost_source = cost_fields(
            None if costed.recording is None else costed.recording.usage
        )
        result = digest(
            costed.result,
            (app.settings.api_key.get_secret_value(),),
            question_names=list(request["questions"]),
        ).model_copy(
            update={
                "cost_usd": cost_usd,
                "cost_source": cost_source,
                "latency_ms": costed.latency_ms,
                "project": costed.project,
            }
        )
        return ToolResult(
            content=render_answers(result), structured_content=result.model_dump(mode="json")
        )

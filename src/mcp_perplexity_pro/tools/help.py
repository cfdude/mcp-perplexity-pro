"""``perplexity_help``: the server's own help as markdown (help-tool spec). Free: no API call,
no usage event, no database, no project."""

from importlib.metadata import version as package_version
from typing import Annotated

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_perplexity_pro import help_text
from mcp_perplexity_pro.errors import PerplexityError

TOOL = "perplexity_help"
ACTIONS = ("index", "tool", "topic")


class HelpResult(BaseModel):
    action: Annotated[str, Field(description="index, tool or topic")]
    name: Annotated[str | None, Field(description="The tool or topic asked for")] = None
    text: Annotated[str, Field(description="The help, as markdown")]
    tools: Annotated[list[str], Field(description="Valid tool names")]
    topics: Annotated[list[str], Field(description="Valid topic names")]


def _bad(message: str) -> PerplexityError:
    return PerplexityError("invalid_request", message)


def register(server: FastMCP) -> None:
    async def perplexity_help(
        ctx: Context,
        action: Annotated[
            str, Field(description="index (default), tool (needs name) or topic (needs name)")
        ] = "index",
        name: Annotated[
            str | None, Field(description="A tool name for tool, a topic name for topic")
        ] = None,
    ) -> ToolResult:
        """How to use this server: start with action index (a short page that picks the right
        tool), then tool with a tool name, or topic (routing, costs, citations, errors,
        projects). Free; makes no API call."""
        if action not in ACTIONS:
            raise _bad(f"action: must be one of {', '.join(ACTIONS)}.")
        settings = ctx.lifespan_context.settings
        listed = {t.name: t for t in await ctx.fastmcp.list_tools()}
        names = sorted(listed)
        try:
            if action == "index":
                text = help_text.render_index(
                    settings, names, package_version("mcp-perplexity-pro")
                )
                name = None
            elif action == "tool":
                chosen = help_text.check_tool(name, [n for n in names if n in help_text.TOOLS])
                tool = listed[chosen]
                annotations = (
                    tool.annotations.model_dump(by_alias=True, exclude_none=True)
                    if tool.annotations
                    else {}
                )
                params = help_text.describe_params(tool.parameters)
                text = help_text.render_tool(chosen, settings, params, annotations)
            else:
                chosen = help_text.check_topic(name)
                text = help_text.render_topic(chosen, settings)
        except help_text.HelpError as exc:
            raise _bad(str(exc)) from None
        result = HelpResult(
            action=action,
            name=name,
            text=text,
            tools=[n for n in names if n in help_text.TOOLS],
            topics=list(help_text.TOPICS),
        )
        return ToolResult(content=text, structured_content=result.model_dump(mode="json"))

    server.tool(
        name=TOOL,
        output_schema=HelpResult.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )(perplexity_help)

"""The help text of the server, as pure functions of plain data.

The MCP tool ``perplexity_help`` and, later, the CLI's ``--help`` print what these functions
return. Nothing here imports FastMCP, a database or an HTTP client: a tool's arguments arrive as
plain dicts built from its JSON schema (``describe_params``), and the settings are read for the
routing mode only. Every dollar figure below must also appear in ``README.md`` (a test checks it),
and every example call must validate against its tool's input schema (a test checks that too).
ASCII only: the index has a byte budget.
"""

from __future__ import annotations

from typing import Any, TypedDict

from mcp_perplexity_pro.settings import Settings, tier_runs

# The closing sentence of the largest tool descriptions (agent-help).
POINTER = " Details: call perplexity_help."

TOPICS = ("routing", "costs", "citations", "errors", "projects")


class HelpError(Exception):
    """An unknown tool or topic name; the message lists the valid ones."""


class ToolHelp(TypedDict):
    summary: str
    billed: bool
    kind: str  # one short cost class for the index
    cost: str
    example: dict[str, Any]
    result: dict[str, list[str]]
    errors: list[tuple[str, str]]


TOOLS: dict[str, ToolHelp] = {
    "perplexity_ask": {
        "summary": "One web-grounded question, answered now, with its sources. No memory.",
        "billed": True,
        "kind": "billed",
        "cost": "Default model perplexity/sonar: $0.00336 in one sample. depth fast: $0.00118 "
        "to $0.00180 over four observations, about 2 s. Every call is recorded as spend.",
        "example": {"query": "What is the latest stable Python release?", "depth": "fast"},
        "result": {"always": ["answer", "sources", "routing", "usage", "model", "depth"]},
        "errors": [
            (
                "invalid_request",
                "Pass only one of depth, tier and model; depth is fast, low or "
                "medium (high and xhigh belong to perplexity_research).",
            ),
            (
                "authentication",
                "The API key is wrong; the server must be restarted with a valid one.",
            ),
        ],
    },
    "perplexity_chat": {
        "summary": "A conversation kept in the local database: send, list, read, delete.",
        "billed": True,
        "kind": "billed; list/read/delete free",
        "cost": "A send costs like perplexity_ask. list, read and delete make no API call.",
        "example": {"action": "send", "title": "Teal notes", "message": "Remember: teal."},
        "result": {
            "send": ["answer", "chat_id", "continuation", "routing", "usage"],
            "list": ["chats", "chats_total"],
            "read": ["messages", "messages_total"],
        },
        "errors": [
            ("invalid_request", "A first send needs a title; a delete needs confirm true."),
            ("not_found", "That chat or project does not exist; use list to see them."),
        ],
    },
    "perplexity_research": {
        "summary": "Starts a deep research run in the background and returns a job id at once.",
        "billed": True,
        "kind": "billed, async",
        "cost": "medium: $0.01599 to $0.02524 per run over four runs, 39 to about 90 s. high and "
        "xhigh were never run: expect dollars and minutes.",
        "example": {"query": "Compare three vector databases by price.", "depth": "medium"},
        "result": {"always": ["job_id", "status", "depth", "message"]},
        "errors": [
            (
                "invalid_request",
                "depth is medium, high or xhigh; too many runs at once is refused.",
            ),
        ],
    },
    "perplexity_jobs": {
        "summary": "Follows research runs: list, status, result, cancel. Observing a finished "
        "run records its cost.",
        "billed": False,
        "kind": "free; records a finished run",
        "cost": "No charge of its own; the first call that sees a run finish records the run's "
        "cost. A run nobody observes is never recorded.",
        "example": {"action": "status", "job_id": 1},
        "result": {"always": ["action", "status", "job", "jobs", "answer", "usage"]},
        "errors": [("not_found", "No such job in that project; use action list.")],
    },
    "perplexity_search": {
        "summary": "Ranked web results as data (title, url, snippet, date). No model answer.",
        "billed": True,
        "kind": "billed",
        "cost": "$0.001 per fast request, $0.005 per web request, however many queries it merges.",
        "example": {"query": "python packaging guide", "search_type": "fast", "max_results": 3},
        "result": {"always": ["results", "count", "cost_usd", "search_type"]},
        "errors": [("invalid_request", "Up to five queries; filters are checked before any call.")],
    },
    "perplexity_decide": {
        "summary": "Calibrated answers to typed questions about a text (noul, choice, score).",
        "billed": True,
        "kind": "billed",
        "cost": "Billed per input token; the result carries the cost.",
        "example": {
            "state": {"ticket": "App crashes on export"},
            "questions": {
                "urgent": {"type": "noul", "criteria": {"true": "blocks work", "false": "does not"}}
            },
        },
        "result": {"always": ["answers", "model", "cost_usd", "warnings"]},
        "errors": [("invalid_request", "1 to 32 questions; each has a type and its criteria.")],
    },
    "perplexity_embed": {
        "summary": "A local vector store: index texts, chats or reports, then search by meaning.",
        "billed": True,
        "kind": "billed; status/delete free",
        "cost": "index and search send text to the API and cost per token; status and delete do "
        "not call it. Vectors are never returned.",
        "example": {"action": "search", "query": "how do I bake bread", "top_k": 3},
        "result": {
            "search": ["hits", "candidates", "cost_usd"],
            "index": ["embedded_chunks", "remaining", "cost_usd"],
        },
        "errors": [("confirmation_required", "delete needs confirm true.")],
    },
    "perplexity_models": {
        "summary": "The live model list with prices, the documented presets, the active routing.",
        "billed": False,
        "kind": "free",
        "cost": "Free; it calls the models endpoint, which is not billed.",
        "example": {"provider": "perplexity"},
        "result": {"always": ["models", "providers", "routing", "presets", "stale"]},
        "errors": [("authentication", "The API key is wrong.")],
    },
    "perplexity_projects": {
        "summary": "List projects, or delete one with its stored records (spend history is kept).",
        "billed": False,
        "kind": "free; delete can delete",
        "cost": "Free. Deleting needs confirm true and cannot be undone.",
        "example": {"action": "list"},
        "result": {"always": ["action", "projects", "rows_removed", "rows_retained"]},
        "errors": [("confirmation_required", "delete needs confirm true.")],
    },
    "perplexity_usage": {
        "summary": "A read-only spend report over everything this server has recorded.",
        "billed": False,
        "kind": "free",
        "cost": "Free. Totals are a lower bound: a call whose cost is unknown counts as zero.",
        "example": {"group_by": "tool"},
        "result": {"always": ["totals", "groups", "group_by", "project"]},
        "errors": [("invalid_request", "group_by is tool, api, model, project or day.")],
    },
    "perplexity_help": {
        "summary": "This help: an index, one tool's page, or a topic. Free, no API call.",
        "billed": False,
        "kind": "free",
        "cost": "Free; it reads no API and writes no record.",
        "example": {"action": "index"},
        "result": {"always": ["action", "name", "text", "tools", "topics"]},
        "errors": [
            ("invalid_request", "action is index, tool or topic; tool and topic need name.")
        ],
    },
}

# Pointers an agent needs first, one line each; the index shows the first five.
DECISIONS = (
    ("A quick grounded fact", "perplexity_ask"),
    ("A report that takes minutes", "perplexity_research, then perplexity_jobs"),
    ("Links and snippets, no answer", "perplexity_search"),
    ("A follow-up conversation", "perplexity_chat"),
    ("Classify a text", "perplexity_decide"),
)

ERROR_FIXES: dict[str, str] = {
    "invalid_request": "Fix the argument the message names; it is usually checked before any "
    "call, and an upstream 400 means the API rejected it.",
    "authentication": "The API key is rejected; tell the operator.",
    "forbidden": "The key lacks access to this feature; tell the operator.",
    "not_found": "The chat, job or project does not exist; list first.",
    "rate_limited": "Wait and retry; a Retry-After shorter than the cap was already honored.",
    "upstream_failure": "Perplexity failed; retry later, a billed call is recorded.",
    "network_timeout": "The call timed out; it may still have been billed, check perplexity_usage.",
    "unexpected_response": "The reply could not be used; it was recorded; retry or report it.",
    "confirmation_required": "Repeat the call with confirm true if you mean it.",
    "storage_busy": "The local database is busy; retry shortly.",
    "internal_error": "A server bug; the real error is in the server log.",
}


def _type_of(schema: dict[str, Any]) -> str:
    if "enum" in schema:
        names = [str(v) for v in schema["enum"]]
        return ", ".join(names[:-1]) + " or " + names[-1] if len(names) > 1 else names[0]
    options = schema.get("anyOf") or schema.get("oneOf")
    if options:
        return " or ".join(_type_of(o) for o in options)
    kind = schema.get("type", "any")
    if isinstance(kind, list):
        return " or ".join(kind)
    if kind == "array":
        return "list of " + _type_of(schema.get("items", {}))
    return str(kind)


def describe_params(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """The arguments of a tool as plain dicts, read from its JSON input schema."""
    required = set(schema.get("required") or [])
    return [
        {
            "name": name,
            "type": _type_of(spec),
            "required": name in required,
            "description": str(spec.get("description", "")),
        }
        for name, spec in (schema.get("properties") or {}).items()
    ]


def check_tool(name: object, valid: list[str]) -> str:
    if not isinstance(name, str) or name not in valid:
        raise HelpError(f"name: must be one of {', '.join(sorted(valid))}.")
    return name


def check_topic(name: object) -> str:
    if not isinstance(name, str) or name not in TOPICS:
        raise HelpError(f"name: must be one of {', '.join(TOPICS)}.")
    return name


def _routing_line(settings: Settings) -> str:
    if settings.routing == "dynamic":
        return (
            "Routing: dynamic, the server picks a tier from the prompt (light "
            f"{tier_runs(settings, 'light')}, standard {tier_runs(settings, 'standard')}, "
            f"complex {tier_runs(settings, 'complex')})."
        )
    if settings.routing == "custom":
        return (
            f"Routing: custom, tiers light {settings.tier_light}, standard "
            f"{settings.tier_standard}, complex {settings.tier_complex}."
        )
    return f"Routing: standard, default model {settings.model}."


def render_index(
    settings: Settings, tool_names: list[str], version: str, style: str = "mcp"
) -> str:
    """The first page: what is here and which tool to pick. At most 1500 ASCII bytes."""
    lines = [
        f"# perplexity-pro {version}",
        "Web-grounded answers, search, decisions and embeddings; every costed call is recorded.",
        _routing_line(settings),
        "",
        "## Pick a tool",
        *(f"- {need}: {tool}" for need, tool in DECISIONS),
        "",
        "## Tools",
    ]
    for name in sorted(tool_names):
        entry = TOOLS.get(name)
        kind = entry["kind"].split(";")[0] if entry else "?"
        lines.append(f"- {name}: {kind}")
    pointer = (
        'More: perplexity_help action="tool" name="<tool>", or action="topic" name="<topic>".'
        if style == "mcp"
        else "More: perplexity-pro help <tool> or help <topic> (a command drops the perplexity_ "
        "prefix: ask, search)."
    )
    lines += ["", "## Topics", ", ".join(TOPICS), "", pointer]
    return "\n".join(lines) + "\n"


def render_tool(
    name: str,
    settings: Settings,
    params: list[dict[str, Any]],
    annotations: dict[str, Any],
    example: str | None = None,
) -> str:
    """One tool's page: purpose, flags, cost, example, arguments, result keys, errors.

    ``example`` replaces the MCP-style JSON example line (the CLI passes its command line)."""
    entry = TOOLS[name]
    if annotations.get("readOnlyHint"):
        flags = "free, read-only"
    else:
        flags = "billed" if entry["billed"] else "free"
        if "async" in entry["kind"]:
            flags += ", asynchronous"
        if annotations.get("destructiveHint"):
            flags += ", some actions can delete data"
    lines = [f"# {name}", entry["summary"], "", f"Flags: {flags}.", f"Cost: {entry['cost']}", ""]
    lines.append("## Example")
    lines.append(
        example
        if example is not None
        else f'{{"name": "{name}", "arguments": {_json(entry["example"])}}}'
    )
    lines += ["", "## Arguments"]
    for p in params:
        need = "required" if p["required"] else "optional"
        text = f" - {p['description']}" if p["description"] else ""
        lines.append(f"- {p['name']} ({p['type']}, {need}){text}")
    lines += ["", "## Result keys"]
    lines += [f"- {label}: {', '.join(keys)}" for label, keys in entry["result"].items()]
    lines += ["", "## Errors"]
    lines += [f"- {category}: {fix}" for category, fix in entry["errors"]]
    if name in ("perplexity_ask", "perplexity_chat"):
        lines += ["", _routing_line(settings)]
    return "\n".join(lines) + "\n"


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=True)


def render_topic(name: str, settings: Settings) -> str:
    check_topic(name)
    return {
        "routing": _routing_topic,
        "costs": _costs_topic,
        "citations": _citations_topic,
        "errors": _errors_topic,
        "projects": _projects_topic,
    }[name](settings)


def _routing_topic(settings: Settings) -> str:
    if settings.routing == "dynamic":
        modes = (
            "Mode dynamic. A call that names nothing is classified from the prompt by fixed "
            "rules (no API call, no cost) and runs a tier: "
            f"light = {tier_runs(settings, 'light')} (short lookups), "
            f"standard = {tier_runs(settings, 'standard')} (everyday), "
            f"complex = {tier_runs(settings, 'complex')} (analysis, long or multi-part prompts). "
            "A chat follow-up never runs below the tier its chat last used. search false runs the "
            "standard tier's model, because a preset always searches. tier, depth or model "
            "overrides the choice. high and xhigh are never picked."
        )
    elif settings.routing == "custom":
        modes = (
            f"Mode custom. Three tiers: light = {settings.tier_light} (light or agent work), "
            f"standard = {settings.tier_standard} (everyday, the default), complex = "
            f"{settings.tier_complex} (deeper reasoning). Pass tier to pick one."
        )
    else:
        modes = (
            f"Mode standard. A call that names nothing uses {settings.model} with web search. "
            "tier works only in custom mode."
        )
    return (
        "# Routing\n"
        f"{modes}\n"
        "The mode is only a default. An explicit model is always used exactly as given, in every "
        "mode. depth (fast, low, medium) picks a Perplexity preset instead. depth, tier and "
        "model cannot be combined: pass one, or none for the default. perplexity_research is not "
        "routed: it always runs a preset.\n"
        "Every ask and chat result has routing: mode, tier, model and selected_by (default, tier, "
        "depth, model or classifier)"
        + (
            ", plus classifier and reason, which say which tier was picked and why.\n"
            if settings.routing == "dynamic"
            else ".\n"
        )
    )


def _costs_topic(settings: Settings) -> str:
    return (
        "# Costs\n"
        "There is no spending cap. Every call is recorded; perplexity_usage shows the total, "
        "which is a lower bound (a call with unknown cost counts zero).\n"
        "- ask and chat, default model perplexity/sonar: $0.00336 for one question (one sample); "
        "$0.00371 with a json_schema (one sample). The default model's cost differs from the "
        "per-depth figures below.\n"
        "- depth fast: $0.00118 to $0.00180, four observations, about 2 s.\n"
        "- depth low: $0.00045 to $0.00386, three observations; a call that fetches a page costs "
        "more.\n"
        "- research medium: $0.01599 to $0.02524, four runs, 39 to about 90 s. high and xhigh "
        "were never run.\n"
        "- search: $0.001 per fast request, $0.005 per web request.\n"
        "Cost follows how many searches and fetches a run makes, so it depends on the question.\n"
    )


def _citations_topic(settings: Settings) -> str:
    return (
        "# Citations\n"
        "sources lists what the run found or fetched, not a citation of each claim. An answer "
        "marker [N] or [web:N] equals a source's ids entry; one URL can carry several ids; a "
        "fetched page has no id. Structured answers (answer_json) have trailing markers removed "
        "from their string values; the answer text is unchanged. fast depth can be overconfident: "
        "check the sources of anything that matters.\n"
    )


def _errors_topic(settings: Settings) -> str:
    lines = ["# Errors", "Every failure has a category; the message says what to change."]
    lines += [f"- `{category}`: {fix}" for category, fix in ERROR_FIXES.items()]
    return "\n".join(lines) + "\n"


def _projects_topic(settings: Settings) -> str:
    return (
        "# Projects\n"
        "Every stored record (chat, research job, embedding) belongs to a project; the default is "
        "default. A project is created by the first costed call that stores something. Reading "
        "(list, read, status) never creates one. The delete action removes a project, its chats, "
        "jobs and vectors but keeps the spend history, detached and still reportable by name.\n"
    )

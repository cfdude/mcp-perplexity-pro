"""Shared Agent API logic for the four tools (design D2 to D4, D14).

* Request side (pure, no I/O): ``AskOptions`` and ``build_request`` validate every option the
  probe showed the API accepts wrongly or reports misleadingly, then build the request body.
* Response side: ``digest`` and the upstream-text cleaner.
* The one costed-call sequence: ``run_costed``.

Everything that can fail on a caller's input raises ``PerplexityError("invalid_request", ...)``
naming the option, so a tool validates first and nothing is sent, recorded or created for a bad
call.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from mcp_perplexity_pro.errors import PerplexityError

# Depths a caller of ask or chat may pick; high and xhigh belong to perplexity_research (D2).
ASK_DEPTHS = ("fast", "low", "medium")
DEFAULT_DEPTH = "fast"
LONG_DEPTHS = ("high", "xhigh")
RECENCIES = ("hour", "day", "week", "month", "year")

# This server's own sanity caps (chosen, not provider limits).
MAX_TEXT_CHARS = 20000  # a query or a chat message
MAX_INSTRUCTIONS_CHARS = 10000
MAX_OUTPUT_TOKENS = 64000
MAX_DOMAINS = 20
MAX_RESULTS = 50

ANTHROPIC_PREFIX = "anthropic/"
ANTHROPIC_DEFAULT_CAP = 4096  # the API rejects an Anthropic model without a cap
EXPLICIT_MODEL_MAX_STEPS = 3  # the only step budget this server ever sends
SCHEMA_NAME = "answer"

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_COUNTRY = re.compile(r"[A-Za-z]{2}", re.ASCII)
_WHITESPACE = re.compile(r"\s")


def _bad(option: str, message: str) -> PerplexityError:
    return PerplexityError("invalid_request", f"{option}: {message}")


def check_text(name: str, value: object, limit: int = MAX_TEXT_CHARS) -> str:
    """A caller's text (query, message, title): a string, not blank, at most ``limit``
    characters. Returned as given."""
    if not isinstance(value, str) or not value.strip():
        raise _bad(name, "must be a non-empty string.")
    if len(value) > limit:
        raise _bad(name, f"must be at most {limit} characters (got {len(value)}).")
    return value


@dataclass(frozen=True)
class AskOptions:
    """The typed options of ask, shared by chat send (design D2). ``depth`` is None when not
    given: the default is ``fast`` unless a ``model`` replaces the preset."""

    depth: str | None = None
    model: str | None = None
    search: bool | None = None
    domains: list[str] | None = None
    recency: str | None = None
    after: str | None = None
    before: str | None = None
    country: str | None = None
    max_results: int | None = None
    instructions: str | None = None
    max_output_tokens: int | None = None
    json_schema: dict[str, Any] | None = None

    @property
    def preset(self) -> str | None:
        """The preset the request names, or None when an explicit model replaces it."""
        if self.model is not None:
            return None
        return self.depth or DEFAULT_DEPTH


def _int_in(option: str, value: object, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _bad(option, f"must be a whole number from {low} to {high}.")
    return value


def _strict_date(option: str, value: str) -> date:
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        raise _bad(option, f"must be a date written YYYY-MM-DD, got {value!r}.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _bad(option, f"is not a real calendar date: {value!r}.") from None


def _domains(value: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(d, str) for d in value):
        raise _bad("domains", "must be a list of domain strings.")
    if len(value) > MAX_DOMAINS:
        raise _bad("domains", f"at most {MAX_DOMAINS} entries are allowed (got {len(value)}).")
    for entry in value:
        if not entry or entry == "-" or _WHITESPACE.search(entry):
            raise _bad("domains", f"entries must be non-empty and hold no whitespace: {entry!r}.")
    denied = [d.startswith("-") for d in value]
    if any(denied) and not all(denied):
        raise _bad(
            "domains",
            "an allowlist and a denylist (entries starting with '-') cannot be mixed; "
            "the API accepts a mixed list but its documentation calls it invalid.",
        )
    return list(value)


def _web_search_tool(options: AskOptions) -> dict[str, Any] | None:
    """The one ``web_search`` tool for the search options given, or None when none is."""
    filters: dict[str, Any] = {}
    if options.domains:
        filters["search_domain_filter"] = _domains(options.domains)
    if options.recency is not None:
        if options.recency not in RECENCIES:
            raise _bad("recency", f"must be one of {', '.join(RECENCIES)}.")
        filters["search_recency_filter"] = options.recency
    after = _strict_date("after", options.after) if options.after is not None else None
    before = _strict_date("before", options.before) if options.before is not None else None
    if after and before and after > before:
        raise _bad("after", "must not be later than before.")
    if after:
        filters["search_after_date_filter"] = after.strftime("%m/%d/%Y")
    if before:
        filters["search_before_date_filter"] = before.strftime("%m/%d/%Y")
    tool: dict[str, Any] = {"type": "web_search"}
    if options.max_results is not None:
        tool["max_results"] = _int_in("max_results", options.max_results, 1, MAX_RESULTS)
    if filters:
        tool["filters"] = filters
    if options.country is not None:
        if not isinstance(options.country, str) or _COUNTRY.fullmatch(options.country) is None:
            raise _bad("country", "must be two ASCII letters, such as US.")
        tool["user_location"] = {"country": options.country.upper()}
    return tool if len(tool) > 1 else None


def build_request(
    options: AskOptions,
    input: str | list[dict[str, Any]],  # noqa: A002 - the API's own field name
    *,
    store: bool,
    background: bool = False,
    previous_response_id: str | None = None,
) -> dict[str, Any]:
    """Validate ``options`` and build the ``POST /v1/agent`` body (design D2).

    Pure: no network, no database. ``input`` is a non-blank string, or the replay list of
    message items. ``store`` is always sent explicitly. Raises ``invalid_request`` naming the
    first option that is wrong.
    """
    if isinstance(input, str):
        valid_input = bool(input.strip())
    else:
        valid_input = isinstance(input, list) and len(input) > 0
    if not valid_input:
        raise _bad("input", "must be a non-blank string (or a non-empty list of messages).")

    if options.depth in LONG_DEPTHS:
        raise _bad(
            "depth",
            f"{options.depth!r} can last minutes and cost dollars: use perplexity_research.",
        )
    if options.depth is not None and options.depth not in ASK_DEPTHS:
        raise _bad("depth", f"must be one of {', '.join(ASK_DEPTHS)}.")
    if options.model is not None:
        if not isinstance(options.model, str) or not options.model.strip():
            raise _bad("model", "must be a non-empty model id.")
        if options.depth is not None:
            raise _bad("depth", "cannot be combined with model: the model replaces the preset.")
    elif options.search is False:
        raise _bad("search", "false needs an explicit model: a preset always searches.")

    search_options = {
        "domains": options.domains,
        "recency": options.recency,
        "after": options.after,
        "before": options.before,
        "country": options.country,
        "max_results": options.max_results,
    }
    if options.search is False:
        given = [name for name, value in search_options.items() if value not in (None, [])]
        if given:
            raise _bad(given[0], "is a search option and cannot be combined with search false.")
        tool = None
    else:
        tool = _web_search_tool(options)

    request: dict[str, Any] = {}
    if options.model is not None:
        request["model"] = options.model
    else:
        request["preset"] = options.depth or DEFAULT_DEPTH
    request["input"] = copy.deepcopy(input)
    if options.instructions is not None:
        if not isinstance(options.instructions, str):
            raise _bad("instructions", "must be a string.")
        if options.instructions.strip():  # blank instructions are the same as none
            request["instructions"] = check_text(
                "instructions", options.instructions, MAX_INSTRUCTIONS_CHARS
            )
    cap = options.max_output_tokens
    if cap is not None:
        cap = _int_in("max_output_tokens", cap, 1, MAX_OUTPUT_TOKENS)
    elif options.model is not None and options.model.startswith(ANTHROPIC_PREFIX):
        cap = ANTHROPIC_DEFAULT_CAP
    if cap is not None:
        request["max_output_tokens"] = cap
    if options.model is not None and options.search is not False:
        # An explicit model searches only when given the tool; it needs a step budget.
        request["tools"] = [tool or {"type": "web_search"}]
        request["max_steps"] = EXPLICIT_MODEL_MAX_STEPS
    elif tool is not None:
        request["tools"] = [tool]  # replaces the preset's own tools (design D2)
    if options.json_schema is not None:
        schema = options.json_schema
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise _bad("json_schema", "must be a JSON Schema object whose root type is 'object'.")
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": SCHEMA_NAME, "schema": copy.deepcopy(schema)},
        }
    if previous_response_id is not None:
        request["previous_response_id"] = previous_response_id
    if background:
        request["background"] = True
    request["store"] = store
    return request

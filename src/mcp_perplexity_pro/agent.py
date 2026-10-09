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
import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.models import AgentRun
from mcp_perplexity_pro.redaction import redact_text
from mcp_perplexity_pro.usage import format_usd, usage_from_agent_response

logger = logging.getLogger(__name__)

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

# Caps for strings that come FROM the API and are stored or returned (design D14).
STATUS_CAP = 64
REASON_CAP = 200
ERROR_TEXT_CAP = 2000
MODEL_CAP = 200

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


# --- Response side (design D3, D14) ----------------------------------------------------------


def clean_text(value: object, cap: int, secrets: Iterable[str] = ()) -> str:
    """Upstream text made safe to store or return: the configured key and key-shaped tokens
    removed FIRST, then cut to ``cap`` characters, so a key straddling the cut leaves no
    fragment (the order the recorder uses). Never raises."""
    return redact_text(value if isinstance(value, str) else str(value), secrets)[:cap]


def clean_status(value: object, secrets: Iterable[str] = ()) -> str:
    return clean_text(value, STATUS_CAP, secrets)


def clean_reason(value: object, secrets: Iterable[str] = ()) -> str:
    return clean_text(value, REASON_CAP, secrets)


def clean_error_text(error: object, secrets: Iterable[str] = ()) -> str:
    """The text of an upstream ``error`` (an object with a ``message``, or a plain string)."""
    if error is None:
        return ""
    if isinstance(error, Mapping):
        message = error.get("message")
        error = message if isinstance(message, str) and message else "the API reported an error"
    return clean_text(error, ERROR_TEXT_CAP, secrets)


class Source(BaseModel):
    url: Annotated[str, Field(description="Page URL")]
    title: Annotated[str | None, Field(description="Page title when known")] = None
    date: Annotated[str | None, Field(description="Publication date when the API gave one")] = None
    id: Annotated[
        int | None, Field(description="The API's result id; absent for fetched pages")
    ] = None


class UsageSummary(BaseModel):
    """What a call used, from the same parser the usage event uses (design D10)."""

    input_tokens: Annotated[int | None, Field(description="Input tokens when reported")] = None
    output_tokens: Annotated[int | None, Field(description="Output tokens when reported")] = None
    total_tokens: Annotated[int | None, Field(description="Total tokens when reported")] = None
    cost_usd: Annotated[
        str | None,
        Field(description="Exact decimal USD cost as a string; null when the cost is unknown"),
    ] = None
    cost_source: Annotated[
        str, Field(description="reported, computed or none (unknown, not free)")
    ] = "none"


def usage_summary(usage: object) -> UsageSummary:
    """A ``UsageSummary`` of a raw ``usage`` mapping (None and malformed values are unknown)."""
    parsed = usage_from_agent_response(usage)
    return UsageSummary(
        input_tokens=parsed.input_tokens,
        output_tokens=parsed.output_tokens,
        total_tokens=parsed.total_tokens,
        cost_usd=format_usd(parsed.cost_nano_usd) if parsed.cost_source != "none" else None,
        cost_source=parsed.cost_source,
    )


class Digest(BaseModel):
    """The tool-facing reading of one run (the part of ``AskResult`` a response decides)."""

    answer: str = ""
    answer_json: Any = None
    sources: list[Source] = Field(default_factory=list)
    status: str = ""
    incomplete_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    model: str | None = None
    response_id: str | None = None
    usage: UsageSummary = Field(default_factory=UsageSummary)


def _answer_text(output: object) -> str:
    """The last ``output_text`` part of the last ``message`` item, else the empty string."""
    if not isinstance(output, list):
        return ""
    messages = [i for i in output if isinstance(i, Mapping) and i.get("type") == "message"]
    if not messages:
        return ""
    content = messages[-1].get("content")
    if not isinstance(content, list):
        return ""
    for part in reversed(content):
        if isinstance(part, Mapping) and part.get("type") == "output_text":
            text = part.get("text")
            return text if isinstance(text, str) else ""
    return ""


def _sources(output: object) -> list[Source]:
    """Search results and fetched pages in output order, de-duplicated by exact URL."""
    if not isinstance(output, list):
        return []
    found: dict[str, Source] = {}
    for item in output:
        if not isinstance(item, Mapping):
            continue
        entries = {"search_results": "results", "fetch_url_results": "contents"}.get(
            item.get("type")  # type: ignore[arg-type]
        )
        rows = item.get(entries) if entries else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            url = row.get("url") if isinstance(row, Mapping) else None
            if not isinstance(url, str) or not url or url in found:
                continue
            title, when, ident = row.get("title"), row.get("date"), row.get("id")
            found[url] = Source(
                url=url,
                title=title if isinstance(title, str) else None,
                date=when if isinstance(when, str) else None,
                id=ident if isinstance(ident, int) and not isinstance(ident, bool) else None,
            )
    return list(found.values())


def _parse_json(text: str) -> tuple[bool, Any]:
    def refuse(name: str) -> Any:
        raise ValueError(name)  # NaN and Infinity are not JSON and could not be returned

    try:
        return True, json.loads(text, parse_constant=refuse)
    except (ValueError, RecursionError):
        return False, None


def digest(
    run: AgentRun | Mapping[str, Any], *, structured: bool = False, secrets: Iterable[str] = ()
) -> Digest:
    """Read a run into the answer, sources, usage summary and warnings (design D3).

    Never raises: ``AgentRun.output`` is ``Any`` on purpose, so a body the API shaped in a way
    nobody recorded yields an empty answer rather than an error that would hide a billed call.
    ``structured`` says a ``json_schema`` was sent, so the text is parsed into ``answer_json``.
    Upstream-originated strings (status, reason, model, id) are redacted and capped; the answer
    and the sources are content and are returned as received.
    """
    secrets = tuple(secrets)
    try:
        body = run if isinstance(run, Mapping) else run.model_dump(mode="json")
        status = clean_status(body.get("status", ""), secrets)
        details = body.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, Mapping) else None
        reason_text = clean_reason(reason, secrets) if isinstance(reason, str) and reason else None
        answer = _answer_text(body.get("output"))
        warnings: list[str] = []
        if status == "incomplete":
            why = f" (reason: {reason_text})" if reason_text else ""
            warnings.append(f"The answer was cut short{why}; the call was billed.")
        answer_json: Any = None
        if structured:
            parsed, value = _parse_json(answer) if answer else (False, None)
            answer_json = value if parsed else None
            if not parsed and status != "incomplete":
                warnings.append("The answer is not valid JSON, so answer_json is null.")
        model, ident = body.get("model"), body.get("id")
        return Digest(
            answer=answer,
            answer_json=answer_json,
            sources=_sources(body.get("output")),
            status=status,
            incomplete_reason=reason_text,
            warnings=warnings,
            model=clean_text(model, MODEL_CAP, secrets) if isinstance(model, str) else None,
            response_id=clean_text(ident, 128, secrets) if isinstance(ident, str) else None,
            usage=usage_summary(body.get("usage")),
        )
    except Exception:  # total by contract: a malformed body must not hide a billed call
        logger.warning("agent digest: response could not be read", exc_info=True)
        return Digest(warnings=["The response could not be read."])

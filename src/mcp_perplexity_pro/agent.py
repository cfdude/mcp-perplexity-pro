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

import asyncio
import copy
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.models import AgentRun
from mcp_perplexity_pro.redaction import redact_text
from mcp_perplexity_pro.storage import jobs as job_store
from mcp_perplexity_pro.storage.models import ResearchJob
from mcp_perplexity_pro.storage.projects import (
    DEFAULT_PROJECT,
    get_or_create_project,
    validate_project_name,
)
from mcp_perplexity_pro.storage.session import is_busy_error, unit_of_work
from mcp_perplexity_pro.usage import (
    agent_response_status,
    format_usd,
    record_usage,
    usage_from_agent_response,
)

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


# --- The one costed-call sequence (design D4) -----------------------------------------------

# A run in one of these states is finished (a non-null ``error`` also finishes it, whatever the
# status says). Anything else on a background run is still going, or is a status nobody recorded.
TERMINAL_STATUSES = ("completed", "failed", "incomplete", "cancelled")


def is_terminal(status: object, error: object) -> bool:
    return status in TERMINAL_STATUSES or error is not None


@dataclass(frozen=True)
class CostedRun:
    """What ``run_costed`` hands back: the run, the measured latency, the project name used,
    and the status the usage event carries (``None`` when no event was attempted)."""

    run: AgentRun
    latency_ms: int
    project: str
    event_status: str | None


async def run_costed(
    app: Any,
    *,
    tool: str,
    project: str | None,
    body: dict[str, Any],
    preset: str | None,
    background: bool,
    resolve_project: bool = True,
) -> CostedRun:
    """Create a run and record it: the recorder contract of ``CLAUDE.md`` "How to record usage".

    ``app`` is the ``AppContext`` (``.settings``, ``.client``, ``.engine``). The order is fixed:

    1. validate the project name (pure);
    2. commit the project in a short write unit (``resolve_project=False`` skips it for a caller
       that has already found its project);
    3. the timed upstream call, holding NO write unit;
    4. ``record_usage`` (its own unit) while no write unit is open: a failure is recorded with its
       category and re-raised; a response is recorded by ``agent_response_status``'s rule;
    5. a synchronous run that is neither ``completed`` nor ``incomplete``, or carries an
       ``error``, raises ``unexpected_response`` naming the status, AFTER its recording.

    A background submit records only a terminal body (a queued or unknown status is returned
    unrecorded and never raised: the caller owns what a submit means). The caller's own write
    comes after this returns. This and the job observation are the only ``record_usage`` call
    sites.
    """
    name = validate_project_name(project or DEFAULT_PROJECT)
    if resolve_project:
        async with unit_of_work(app.engine) as session:  # short, committed before the call
            await get_or_create_project(session, name)
    secrets = (app.settings.api_key.get_secret_value(),)
    started = time.monotonic()
    try:
        run = await app.client.create_run(body, background=background)
    except PerplexityError as exc:
        await record_usage(
            app.engine,
            tool=tool,
            api="agent",
            status=exc.category,
            preset=preset,
            project=name,
            latency_ms=_ms(started),
            secrets=secrets,
        )
        raise
    latency = _ms(started)
    raw = run.model_dump(mode="json")
    status = agent_response_status(raw)
    if background and not is_terminal(raw.get("status"), raw.get("error")):
        status = None  # a submit that has not finished: nothing to record yet
    if status is not None:
        await record_usage(
            app.engine,
            tool=tool,
            api="agent",
            status=status,
            usage=raw.get("usage"),  # the raw mapping: the recorder parses it
            model=snapshot_model(raw, preset) if background else raw.get("model"),
            preset=preset,
            request_id=raw.get("id"),
            project=name,
            latency_ms=latency,
            secrets=secrets,
        )
    if not background and (
        raw.get("status") not in ("completed", "incomplete") or raw.get("error") is not None
    ):
        detail = clean_error_text(raw.get("error"), secrets)
        raise PerplexityError(
            "unexpected_response",
            f"The API returned status {clean_status(raw.get('status'), secrets)!r} instead of a "
            "finished answer" + (f": {detail}" if detail else "."),
            secrets=secrets,
        )
    return CostedRun(run=run, latency_ms=latency, project=name, event_status=status)


def _ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


# --- Background research (design D7 to D9) --------------------------------------------------

RESEARCH_TOOL = "perplexity_research"
RESEARCH_DEPTHS = ("medium", "high", "xhigh")
DEFAULT_RESEARCH_DEPTH = "medium"
LOST_AFTER = timedelta(minutes=10)  # a chosen margin for propagation delay, not measured
REFRESH_LIMIT = 10


def build_research_request(
    depth: object, query: object, instructions: object = None
) -> dict[str, Any]:
    """The ``POST /v1/agent`` body of a research run (design D2). Pure; raises
    ``invalid_request`` naming the option. ``background`` and ``store`` are both always true:
    a background run with ``store`` false cannot be retrieved, so its result and cost would be
    lost, and the tool offers no way to send false."""
    if depth not in RESEARCH_DEPTHS:
        raise _bad(
            "depth",
            f"must be one of {', '.join(RESEARCH_DEPTHS)}; fast and low answers belong to "
            "perplexity_ask.",
        )
    request: dict[str, Any] = {"preset": depth, "input": check_text("query", query)}
    if instructions is not None:
        if not isinstance(instructions, str):
            raise _bad("instructions", "must be a string.")
        if instructions.strip():  # blank instructions are the same as none
            request["instructions"] = check_text(
                "instructions", instructions, MAX_INSTRUCTIONS_CHARS
            )
    request["background"] = True
    request["store"] = True
    return request


def snapshot_model(raw: Mapping[str, Any], depth: str | None) -> str | None:
    """The model of a snapshot, or None when it is not known (design D7). The API reports the
    preset NAME (``medium``) as ``model`` on queued, in-progress and cancelled snapshots; that
    is not a model. Known only from a ``completed`` snapshot, or a value that contains ``/``
    and differs from the job's depth."""
    model = raw.get("model")
    if not isinstance(model, str) or not model:
        return None
    if raw.get("status") == "completed" or ("/" in model and model != depth):
        return model
    return None


def terminal_status(status: object, error: object) -> str:
    """The status stored for a finished run: the API's own when it belongs to the vocabulary the
    terminal test knows, else ``failed`` (an error on any other status, or on ``completed``)."""
    if error is None:
        return str(status)
    return status if status in ("failed", "incomplete", "cancelled") else "failed"  # type: ignore[return-value]


def search_progress(raw: Mapping[str, Any]) -> tuple[int, int]:
    """How many search and fetch steps a snapshot has shown: output items of each kind."""
    output = raw.get("output")
    if not isinstance(output, list):
        return 0, 0
    kinds = [i.get("type") for i in output if isinstance(i, Mapping)]
    return kinds.count("search_results"), kinds.count("fetch_url_results")


def job_columns(
    raw: Mapping[str, Any], depth: str, now: datetime, secrets: Iterable[str] = ()
) -> dict[str, Any]:
    """The ``research_jobs`` column values a snapshot decides. Only OUR times are stored: the
    API rewrites its own ``created_at`` and ``completed_at`` on every fetch (design D7).

    A running snapshot gives its status (verbatim, redacted, cut to 64) and the model when it is
    known. A terminal one also gives the finish time, the answer and sources when present, the
    reason, the error text, the usage summary, and ``usage_recorded`` 1: the caller records the
    event BEFORE writing these (design D8)."""
    secrets = tuple(secrets)
    error = raw.get("error")
    model = snapshot_model(raw, depth)
    values: dict[str, Any] = {
        "status": clean_status(raw.get("status", ""), secrets),
        "last_checked_at": now,
        "missing_since": None,
    }
    if model is not None:
        values["model"] = clean_text(model, MODEL_CAP, secrets)
    if not is_terminal(raw.get("status"), error):
        return values
    read = digest(raw, secrets=secrets)
    usage = usage_from_agent_response(raw.get("usage"))
    values.update(
        status=terminal_status(raw.get("status"), error),
        finished_at=now,
        result_text=read.answer or None,
        sources_json=json.dumps([s.model_dump() for s in read.sources]) if read.sources else None,
        incomplete_reason=read.incomplete_reason,
        error_text=clean_error_text(error, secrets) if error is not None else None,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        cost_nano_usd=usage.cost_nano_usd,
        cost_source=usage.cost_source,
        usage_recorded=1,
    )
    return values


def stored_usage(job: ResearchJob) -> UsageSummary:
    """The ``UsageSummary`` of a finished job, read from the stored columns (design D10)."""
    known = job.cost_source not in (None, "none") and job.cost_nano_usd is not None
    return UsageSummary(
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        total_tokens=job.total_tokens,
        cost_usd=format_usd(job.cost_nano_usd) if known else None,  # type: ignore[arg-type]
        cost_source=job.cost_source or "none",
    )


def error_category(exc: BaseException) -> str:
    """The category a failure of any kind has on the wire (the server's own mapping)."""
    if isinstance(exc, PerplexityError):
        return exc.category
    if is_busy_error(exc):
        return "storage_busy"
    return "internal_error"


class JobLocks:
    """One in-process ``asyncio.Lock`` per job id, created on demand and dropped when unused
    (design D8). Enough because the server is one process; a second process on the same
    database would reintroduce the window the lock closes."""

    def __init__(self) -> None:
        self._held: dict[int, list[Any]] = {}  # job id -> [lock, users]

    @asynccontextmanager
    async def hold(self, job_id: int) -> AsyncIterator[None]:
        entry = self._held.get(job_id)
        if entry is None:
            entry = self._held[job_id] = [asyncio.Lock(), 0]
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                del self._held[job_id]


@dataclass
class Observation:
    """What one observation of a job found.

    ``job`` is the row as stored afterwards, ``state`` the status to report (the stored one,
    ``lost`` included), ``run`` the snapshot fetched (None when the stored row was returned
    without a fetch, or the provider did not know the run) and ``warnings`` what the caller
    should show."""

    job: ResearchJob
    state: str
    run: dict[str, Any] | None = None
    fetched: bool = False
    warnings: list[str] = field(default_factory=list)


async def _write_job(app: Any, project_id: int, job_id: int, values: dict[str, Any]) -> ResearchJob:
    async with unit_of_work(app.engine) as session:  # its own unit; nothing else shares it
        return await job_store.update_job(session, project_id, job_id, values)


async def observe_job(app: Any, *, project_id: int, project: str, job_id: int) -> Observation:
    """Observe one job: fetch it and store what it shows (design D7, D8, D9). The SECOND
    ``record_usage`` call site (the first is ``run_costed``).

    Under the job's in-process lock, the stored row is RE-READ and a final one (or one whose
    usage is already recorded) is returned with no fetch. Otherwise the run is fetched once:

    * the provider does not know it (``not_found``): the first time records ``missing_since``;
      a later one, at least 10 minutes after submit, makes the job ``lost`` (no event);
    * a snapshot that is not terminal stores its status (verbatim) and the model when known;
    * a terminal snapshot is recorded FIRST (the recorder's own unit, no write unit open), then
      its row update is its own unit, so a failing update keeps the event and the next
      observation records the ``ok`` run again into the dedupe index.

    Any other failure propagates; the caller decides (``refresh`` warns, the rest raise).
    """
    secrets = (app.settings.api_key.get_secret_value(),)
    async with app.job_locks.hold(job_id):
        async with unit_of_work(app.engine, write=False) as session:
            job = await job_store.load_job(session, project_id, job_id)
        if job_store.is_final(job):
            return Observation(job, job.status)
        try:
            run = await app.client.get_run(job.response_id)
        except PerplexityError as exc:
            if exc.category != "not_found":
                raise
            return await _missing(app, project_id, job, secrets)
        now = app.now()
        raw = run.model_dump(mode="json")
        if is_terminal(raw.get("status"), raw.get("error")):
            await record_usage(  # NO write unit is open here (the recorder contract)
                app.engine,
                tool=RESEARCH_TOOL,
                api="agent",
                status=agent_response_status(raw) or "unexpected_response",
                usage=raw.get("usage"),
                model=snapshot_model(raw, job.depth),
                preset=job.depth,
                request_id=job.response_id,
                project=project,
                latency_ms=max(round((now - job.started_at).total_seconds() * 1000), 0),
                secrets=secrets,
            )
        job = await _write_job(app, project_id, job_id, job_columns(raw, job.depth, now, secrets))
        return Observation(job, job.status, run=raw, fetched=True)


async def _missing(
    app: Any, project_id: int, job: ResearchJob, secrets: tuple[str, ...]
) -> Observation:
    """The provider answered ``not_found`` for a job that is not final (design D7): never proof
    the run is gone, so the first time only records when, and ``lost`` needs a second."""
    now = app.now()
    if job.missing_since is not None and now - job.started_at >= LOST_AFTER:
        job = await _write_job(
            app, project_id, job.id, {"status": "lost", "finished_at": now, "last_checked_at": now}
        )
        return Observation(
            job,
            "lost",
            warnings=[
                "The provider no longer knows this run, so it is marked lost. Its spend was not "
                "recorded and cannot be: the run's cost is unknown."
            ],
        )
    if job.missing_since is None:
        job = await _write_job(app, project_id, job.id, {"missing_since": now})
    return Observation(
        job,
        job.status,
        warnings=[
            "The provider did not find this run (not_found). It is treated as still running: "
            f"a later not_found at least {int(LOST_AFTER.total_seconds() // 60)} minutes after "
            "submit marks it lost."
        ],
    )

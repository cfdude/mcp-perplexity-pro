"""Search API logic for ``perplexity_search`` (design D2 to D5, D9).

* Request side (pure, no I/O): ``SearchOptions`` and ``build_request`` validate every option the
  probe showed the API accepts wrongly, then build the ``POST /search`` body.
* Response side: ``digest`` and the output models, ``search_usage`` (the one price-tier choice)
  and ``run_search`` (the caller of ``costed.costed_call``).

Everything that can fail on a caller's input raises ``PerplexityError("invalid_request", ...)``
naming the option, so the tool validates first and nothing is sent, recorded or created for a
bad call. The validators are the Agent tool's own (imported, never copied).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mcp_perplexity_pro import pricing
from mcp_perplexity_pro.agent import (
    _COUNTRY,
    DATE_CAP,
    RECENCIES,
    _bad,
    _domains,
    _int_in,
    _strict_date,
    check_text,
)
from mcp_perplexity_pro.costed import Costed, Recording, costed_call
from mcp_perplexity_pro.models import SearchResponse
from mcp_perplexity_pro.redaction import redact_text, scrub_secrets
from mcp_perplexity_pro.usage import Usage, computed_usage, format_usd

logger = logging.getLogger(__name__)

TOOL = "perplexity_search"

SEARCH_TYPES = ("fast", "web")
DEFAULT_SEARCH_TYPE = "fast"
MAX_QUERIES = 5
MAX_QUERY_CHARS = 8192
MAX_RESULTS = 20  # the Search API refuses 21 for both types
MAX_TOKENS = 16384  # our own cap; the API's maximum is not documented
MAX_PAGE_TOKENS = 4096  # our own cap
MAX_LANGUAGES = 20

_LANGUAGE = re.compile(r"[a-z]{2}", re.ASCII)


@dataclass(frozen=True)
class SearchOptions:
    """The typed options of ``perplexity_search``. ``query`` is one string or a list of 1 to 5."""

    query: str | list[str]
    search_type: str = DEFAULT_SEARCH_TYPE
    max_results: int | None = None
    max_tokens: int | None = None
    max_tokens_per_page: int | None = None
    domains: list[str] | None = None
    recency: str | None = None
    after: str | None = None
    before: str | None = None
    updated_after: str | None = None
    updated_before: str | None = None
    languages: list[str] | None = None
    country: str | None = None


def _api_date(value: date) -> str:
    # explicit, not strftime: strftime does not zero-pad the year of a year before 1000
    return f"{value.month:02d}/{value.day:02d}/{value.year:04d}"


def _queries(query: object) -> str | list[str]:
    if isinstance(query, list):
        if not 1 <= len(query) <= MAX_QUERIES:
            raise _bad("query", f"a list must hold 1 to {MAX_QUERIES} queries (got {len(query)}).")
        return [check_text("query", q, MAX_QUERY_CHARS) for q in query]
    return check_text("query", query, MAX_QUERY_CHARS)


def _search_type(value: object) -> str:
    if value == "people":
        raise _bad("search_type", "'people' is not offered by this server.")
    if value not in SEARCH_TYPES:
        raise _bad("search_type", f"must be one of {', '.join(SEARCH_TYPES)}.")
    return str(value)


def _languages(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _bad("languages", "must be a list of two-letter lowercase ISO 639-1 codes.")
    if len(value) > MAX_LANGUAGES:
        raise _bad("languages", f"at most {MAX_LANGUAGES} entries are allowed (got {len(value)}).")
    for code in value:
        if _LANGUAGE.fullmatch(code) is None:
            raise _bad("languages", "each entry must be two lowercase ASCII letters, e.g. 'en'.")
    return list(value)


def _date_pair(
    first_name: str, first: str | None, second_name: str, second: str | None
) -> tuple[date | None, date | None]:
    low = _strict_date(first_name, first) if first is not None else None
    high = _strict_date(second_name, second) if second is not None else None
    if low and high and low > high:
        raise _bad(first_name, f"must not be later than {second_name}.")
    return low, high


def build_request(options: SearchOptions) -> dict[str, Any]:
    """Validate ``options`` and build the ``POST /search`` body. Pure: no network, no database.
    ``search_type`` is always sent (an omitted one runs the dearer ``web`` search). Raises
    ``invalid_request`` naming the first option that is wrong."""
    request: dict[str, Any] = {
        "query": _queries(options.query),
        "search_type": _search_type(options.search_type),
    }
    if options.max_results is not None:
        request["max_results"] = _int_in("max_results", options.max_results, 1, MAX_RESULTS)
    if options.max_tokens is not None:
        request["max_tokens"] = _int_in("max_tokens", options.max_tokens, 1, MAX_TOKENS)
    if options.max_tokens_per_page is not None:
        request["max_tokens_per_page"] = _int_in(
            "max_tokens_per_page", options.max_tokens_per_page, 1, MAX_PAGE_TOKENS
        )
    if options.domains:
        request["search_domain_filter"] = _domains(options.domains)
    elif options.domains is not None:
        _domains(options.domains)  # an empty list is valid and not sent; a non-list is refused
    if options.recency is not None:
        if options.recency not in RECENCIES:
            raise _bad("recency", f"must be one of {', '.join(RECENCIES)}.")
        request["search_recency_filter"] = options.recency
    after, before = _date_pair("after", options.after, "before", options.before)
    updated_after, updated_before = _date_pair(
        "updated_after", options.updated_after, "updated_before", options.updated_before
    )
    if options.recency is not None and any((after, before, updated_after, updated_before)):
        raise _bad("recency", "cannot be combined with a date filter.")
    for field, value in (
        ("search_after_date_filter", after),
        ("search_before_date_filter", before),
        ("last_updated_after_filter", updated_after),
        ("last_updated_before_filter", updated_before),
    ):
        if value is not None:
            request[field] = _api_date(value)
    if options.languages:
        request["search_language_filter"] = _languages(options.languages)
    elif options.languages is not None:
        _languages(options.languages)
    if options.country is not None:
        if not isinstance(options.country, str) or _COUNTRY.fullmatch(options.country) is None:
            raise _bad("country", "must be two ASCII letters, such as US.")
        request["country"] = options.country.upper()
    return request


# --- Response side (design D4, D9) -----------------------------------------------------------

TITLE_CAP = 500
URL_CAP = 2048
SNIPPET_CAP = 20000
REQUEST_ID_CAP = 128
DEFAULT_MAX_RESULTS = 10  # the API's own default count


class SearchResult(BaseModel):
    title: Annotated[str, Field(description="Page title (third-party text; may be empty)")]
    url: Annotated[str, Field(description="Page URL")]
    snippet: Annotated[str, Field(description="Page excerpt (third-party text; may be empty)")]
    date: Annotated[str | None, Field(description="Publication date as given (YYYY-MM-DD)")] = None
    last_updated: Annotated[
        str | None, Field(description="Last-updated date as given (YYYY-MM-DD)")
    ] = None


class SearchOutput(BaseModel):
    results: Annotated[list[SearchResult], Field(description="Ranked results, in the API's order")]
    count: Annotated[int, Field(description="Results kept")]
    query_count: Annotated[int, Field(description="Queries in the request")]
    search_type: Annotated[str, Field(description="fast or web")]
    request_id: Annotated[str | None, Field(description="The API's request id")] = None
    cost_usd: Annotated[
        str | None, Field(description="Exact USD cost of the request, as a decimal string")
    ] = None
    cost_source: Annotated[str, Field(description="computed, or none when the cost is unknown")] = (
        "none"
    )
    latency_ms: Annotated[int, Field(description="Measured wall time of the upstream call")] = 0
    project: Annotated[str, Field(description="The project the call was recorded under")] = ""
    warnings: Annotated[list[str], Field(description="Things worth knowing about this result")]


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _clean(value: object, cap: int, secrets: Iterable[str], cut: list[int]) -> str | None:
    """A third-party string: the configured key replaced, then cut to ``cap`` (counted in
    ``cut``). A value that is not text is None."""
    if not isinstance(value, str):
        return None
    text = scrub_secrets(value, secrets)
    if len(text) > cap:
        cut.append(1)
        text = text[:cap]
    return text


def digest(
    response: SearchResponse,
    secrets: Iterable[str] = (),
    *,
    max_results: int | None = None,
    max_tokens: int | None = None,
    query_count: int = 1,
    search_type: str = DEFAULT_SEARCH_TYPE,
) -> SearchOutput:
    """The tool's result for a response. Total: it never raises (the call is already billed)."""
    secrets = tuple(secrets)
    try:
        cut: list[int] = []
        kept: list[SearchResult] = []
        dropped = 0
        for item in response.results:
            url = _clean(item.get("url"), URL_CAP, secrets, cut) if isinstance(item, dict) else None
            if not url:
                dropped += 1
                continue
            kept.append(
                SearchResult(
                    title=_clean(item.get("title"), TITLE_CAP, secrets, cut) or "",
                    url=url,
                    snippet=_clean(item.get("snippet"), SNIPPET_CAP, secrets, cut) or "",
                    date=_clean(item.get("date"), DATE_CAP, secrets, cut),
                    last_updated=_clean(item.get("last_updated"), DATE_CAP, secrets, cut),
                )
            )
        returned = len(response.results)
        warnings: list[str] = []
        if returned == 0:
            warnings.append("The search returned no results (it is still billed).")
        if dropped:
            warnings.append(
                f"{_plural(dropped, 'result')} dropped: not an object or without a usable url."
            )
        if cut:
            warnings.append(f"{_plural(len(cut), 'field')} cut to this server's size cap.")
        if query_count > 1:
            warnings.append(
                "The API merges the queries into one list and does not say which query produced "
                "which result; make one call per query when you need that."
            )
        if max_tokens is not None and returned < (max_results or DEFAULT_MAX_RESULTS):
            note = (
                f"{returned} results came back, fewer than asked for: max_tokens may have "
                "dropped results to fit its budget."
            )
            if max_results is None:
                note += " The query may also simply have had few hits."
            warnings.append(note)
        request_id = (
            redact_text(response.id, secrets)[:REQUEST_ID_CAP]
            if isinstance(response.id, str)
            else None
        )
        return SearchOutput(
            results=kept,
            count=len(kept),
            query_count=query_count,
            search_type=search_type,
            request_id=request_id,
            warnings=warnings,
        )
    except Exception:  # total by contract: a malformed body must not hide a billed call
        logger.warning("search digest: response could not be read", exc_info=True)
        return SearchOutput(
            results=[],
            count=0,
            query_count=query_count,
            search_type=search_type,
            warnings=["The response could not be read."],
        )


# --- Cost and the one costed call (design D5, D6) --------------------------------------------

PRICE_TIER = {"fast": "fast", "web": "standard"}  # the tool's search type -> the price table's


def search_usage(search_type: str, raw: object = None) -> Usage:
    """The usage of one search request: ONE billing unit at the documented price of its type,
    source ``computed``. A ``usage`` object in the response is kept as ``raw`` and never read as
    a cost. Never raises."""
    try:
        nano = pricing.search_cost_nano(1, PRICE_TIER[search_type])
        raw_usage = dict(raw) if isinstance(raw, Mapping) else None
        if nano is None:
            return Usage(raw=raw_usage)
        return computed_usage(nano, raw=raw_usage)
    except Exception:
        logger.warning("search usage: cost could not be computed", exc_info=True)
        return Usage()


def cost_fields(usage: Usage | Mapping | None) -> tuple[str | None, str]:
    """``(cost_usd, cost_source)`` of a recorded usage, as the output carries them."""
    if isinstance(usage, Usage) and usage.cost_source != "none":
        return format_usd(usage.cost_nano_usd), usage.cost_source
    return None, "none"


async def run_search(
    app: Any, *, project: str | None, body: dict[str, Any], search_type: str
) -> Costed[SearchResponse]:
    """Send ``body`` and record the request (``costed.costed_call``)."""

    def interpret(response: SearchResponse) -> Recording:
        extra = response.model_extra or {}
        return Recording(
            status="ok",
            usage=search_usage(search_type, extra.get("usage")),
            request_id=response.id if isinstance(response.id, str) else None,
        )

    return await costed_call(
        app,
        tool=TOOL,
        api="search",
        project=project,
        preset=None,
        call=lambda: app.client.search(body),
        record=interpret,
    )

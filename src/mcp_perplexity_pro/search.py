"""Search API logic for ``perplexity_search`` (design D2 to D5, D9).

* Request side (pure, no I/O): ``SearchOptions`` and ``build_request`` validate every option the
  probe showed the API accepts wrongly, then build the ``POST /search`` body.

Everything that can fail on a caller's input raises ``PerplexityError("invalid_request", ...)``
naming the option, so the tool validates first and nothing is sent, recorded or created for a
bad call. The validators are the Agent tool's own (imported, never copied).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from mcp_perplexity_pro.agent import (
    _COUNTRY,
    RECENCIES,
    _bad,
    _domains,
    _int_in,
    _strict_date,
    check_text,
)

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

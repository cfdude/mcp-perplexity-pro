"""Tasks 2.1 and 2.2 (py-search-api): ``search.build_request`` against the recorded requests."""

import json
import re
from pathlib import Path

import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.search import SearchOptions, build_request

SRC = Path(__file__).resolve().parent.parent / "src" / "mcp_perplexity_pro"

# API field -> option name
FIELDS = {
    "query": "query",
    "search_type": "search_type",
    "max_results": "max_results",
    "max_tokens": "max_tokens",
    "max_tokens_per_page": "max_tokens_per_page",
    "search_domain_filter": "domains",
    "search_recency_filter": "recency",
    "search_after_date_filter": "after",
    "search_before_date_filter": "before",
    "last_updated_after_filter": "updated_after",
    "last_updated_before_filter": "updated_before",
    "search_language_filter": "languages",
    "country": "country",
}
# Dates are recorded as MM/DD/YYYY; the tool takes YYYY-MM-DD.
DATE_FIELDS = {
    "search_after_date_filter",
    "search_before_date_filter",
    "last_updated_after_filter",
    "last_updated_before_filter",
}


def sidecar(name):
    return json.loads((FIXTURE_DIR / f"{name}.meta.json").read_text())


def options_from(request):
    kwargs = {}
    for field, value in request.items():
        if field in DATE_FIELDS:
            month, day, year = value.split("/")
            value = f"{year}-{month}-{day}"
        kwargs[FIELDS[field]] = value
    return SearchOptions(**kwargs)


COMPARED = [
    "search_fast_single",
    "search_web_single",
    "search_fast_multi_query",
    "search_fast_multi_query_duplicate",
    "search_fast_max_tokens_one",
    "search_fast_max_tokens_per_page",
    "search_fast_page_tokens_above_total",
    "search_fast_allow_domain",
    "search_fast_deny_domain",
    "search_fast_recency_month",
    "search_fast_date_range_inclusive",
    "search_fast_date_range_empty",
    "search_fast_updated_range",
    "search_fast_language_11_accepted",
]
# The recorded 200 requests this tool does not reproduce, each for a stated reason.
REFUSED_ALTHOUGH_ACCEPTED = {
    "search_fast_mixed_domains_accepted": "mixed allow and deny list",
    "search_fast_language_uppercase_accepted": "uppercase language code",
    "search_fast_recency_with_updated_accepted": "recency with a date filter",
    "search_whitespace_query_empty": "blank query",
}
COVERED_ELSEWHERE = {
    "search_omitted_search_type_accepted": "asserted below with search_type fast added",
    "search_unknown_field_accepted": "no option builds bogus_param",
}


@pytest.mark.parametrize("name", COMPARED)
def test_a_recorded_request_is_rebuilt_exactly(name):
    request = sidecar(name)["request"]
    assert build_request(options_from(request)) == request


def test_the_omitted_search_type_request_is_rebuilt_with_fast_added():
    request = sidecar("search_omitted_search_type_accepted")["request"]
    assert "search_type" not in request
    assert build_request(options_from(request)) == {**request, "search_type": "fast"}


def test_every_recorded_200_request_is_compared_or_accounted_for():
    ok = {
        p.name.removesuffix(".meta.json")
        for p in FIXTURE_DIR.glob("search_*.meta.json")
        if json.loads(p.read_text())["http_status"] == 200
    }
    accounted = set(COMPARED) | set(REFUSED_ALTHOUGH_ACCEPTED) | set(COVERED_ELSEWHERE)
    assert ok == accounted


@pytest.mark.parametrize("name", REFUSED_ALTHOUGH_ACCEPTED)
def test_requests_the_api_accepted_but_this_tool_refuses_are_refused(name):
    request = sidecar(name)["request"]
    with pytest.raises(PerplexityError) as caught:
        build_request(options_from(request))
    assert caught.value.category == "invalid_request"


# Shapes with NO sidecar are asserted against inline expected dicts.
def test_the_minimal_request_sends_fast_explicitly():  # inline expected, no sidecar
    assert build_request(SearchOptions(query="python")) == {
        "query": "python",
        "search_type": "fast",
    }


def test_a_list_of_three_queries_is_sent_as_a_list():  # inline expected, no sidecar
    assert build_request(SearchOptions(query=["a", "b", "c"])) == {
        "query": ["a", "b", "c"],
        "search_type": "fast",
    }


def test_country_is_sent_upper_case():  # inline expected, no sidecar
    assert build_request(SearchOptions(query="q", country="us"))["country"] == "US"


def test_a_year_before_1000_is_zero_padded():  # inline expected, no sidecar
    request = build_request(SearchOptions(query="q", after="0999-01-02"))
    assert request["search_after_date_filter"] == "01/02/0999"


def test_empty_domains_and_languages_are_not_sent():
    request = build_request(SearchOptions(query="q", domains=[], languages=[]))
    assert request == {"query": "q", "search_type": "fast"}


def test_mutation_guard_search_type_is_sent_even_when_it_is_the_default():
    assert build_request(SearchOptions(query="q"))["search_type"] == "fast"


REFUSALS = [
    ("query", dict(query="")),
    ("query", dict(query="   ")),
    ("query", dict(query=[])),
    ("query", dict(query=["a"] * 6)),
    ("query", dict(query=["a", " "])),
    ("query", dict(query="x" * 8193)),
    ("max_results", dict(max_results=0)),
    ("max_results", dict(max_results=21)),
    ("max_tokens", dict(max_tokens=0)),
    ("max_tokens", dict(max_tokens=16385)),
    ("max_tokens_per_page", dict(max_tokens_per_page=4097)),
    ("max_tokens_per_page", dict(max_tokens_per_page=0)),
    ("search_type", dict(search_type="people")),
    ("search_type", dict(search_type="deep")),
    ("domains", dict(domains=["python.org", "-reddit.com"])),
    ("domains", dict(domains=[f"a{i}.com" for i in range(21)])),
    ("domains", dict(domains=[""])),
    ("domains", dict(domains=["-"])),
    ("domains", dict(domains=["a" * 254])),
    ("after", dict(after="09/01/2026")),
    ("after", dict(after="2026-13-40")),
    ("after", dict(after="yesterday")),
    ("after", dict(after="2026-02-01", before="2026-01-01")),
    ("updated_after", dict(updated_after="2026-02-01", updated_before="2026-01-01")),
    ("recency", dict(recency="decade")),
    ("recency", dict(recency="week", after="2026-01-01")),
    ("recency", dict(recency="week", updated_after="2026-01-01")),
    ("languages", dict(languages=["eng"])),
    ("languages", dict(languages=["EN"])),
    ("languages", dict(languages=["en"] * 21)),
    ("country", dict(country="USA")),
    ("country", dict(country="1")),
]


@pytest.mark.parametrize(("option", "kwargs"), REFUSALS, ids=lambda v: str(v)[:40])
def test_a_bad_option_is_invalid_request_naming_the_option(option, kwargs):
    kwargs = {"query": "q", **kwargs}
    with pytest.raises(PerplexityError) as caught:
        build_request(SearchOptions(**kwargs))
    assert caught.value.category == "invalid_request"
    assert str(caught.value).startswith(option)


def test_the_validators_are_imported_from_agent_not_copied():
    text = (SRC / "search.py").read_text()
    assert not re.search(r"def (_domains|_strict_date|_int_in|_bad|check_text)\b", text)


def test_the_agent_date_filter_zero_pads_an_early_year_like_search():
    from routing_support import ask_options

    from mcp_perplexity_pro.agent import build_request as agent_request

    request = agent_request(ask_options(after="0999-01-02"), "q", store=False)
    assert request["tools"][0]["filters"]["search_after_date_filter"] == "01/02/0999"

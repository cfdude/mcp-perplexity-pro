"""Task 3.1 (py-search-api): ``search.digest`` and the output models."""

import json

from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.models import SearchResponse
from mcp_perplexity_pro.search import SearchOutput, digest

KEY = "pplx-" + "Zk3Hq8Lm2Vx9Rt5Wy7Nb4Jd6Fc1Sg0A"
EXAMPLE = "pplx-" + "a1B2c3D4e5F6g7H8i9J0k1L2"


def load(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def parse(name):
    return SearchResponse.model_validate(load(name))


def response(*items, id="x"):  # noqa: A002
    return SearchResponse.model_validate({"id": id, "results": list(items)})


def item(**fields):
    return {"title": "t", "url": "https://e.example/a", "snippet": "s", **fields}


def test_a_fast_single_query_keeps_its_five_results_in_order():
    raw = load("search_fast_single.json")
    out = digest(parse("search_fast_single.json"), (KEY,), max_results=5)
    assert isinstance(out, SearchOutput)
    assert out.count == 5 and out.request_id == raw["id"]
    for got, want in zip(out.results, raw["results"], strict=True):
        assert (got.title, got.url, got.snippet) == (want["title"], want["url"], want["snippet"])
        assert got.date == want.get("date") and got.last_updated == want["last_updated"]
    assert out.warnings == []  # nothing cut, nothing dropped, no budget


def test_a_result_without_a_date_has_none_and_keeps_last_updated():
    out = digest(response(item(last_updated="2026-01-01")))
    assert out.results[0].date is None and out.results[0].last_updated == "2026-01-01"


def test_three_queries_keep_the_apis_ten_results_and_say_they_are_merged():
    raw = load("search_fast_multi_query.json")
    out = digest(parse("search_fast_multi_query.json"), (), max_results=10, query_count=3)
    assert [r.url for r in out.results] == [r["url"] for r in raw["results"]] and out.count == 10
    assert out.query_count == 3
    assert any("merges the queries" in w for w in out.warnings)
    single = digest(parse("search_fast_multi_query.json"), (), max_results=10, query_count=1)
    assert not any("merges" in w for w in single.warnings)


def test_an_empty_response_is_count_zero_with_a_warning():
    out = digest(parse("search_fast_date_range_empty.json"), ())
    assert out.count == 0 and out.request_id and any("no results" in w for w in out.warnings)


def test_a_budget_that_dropped_results_warns_naming_max_tokens():
    out = digest(parse("search_fast_max_tokens_one.json"), (), max_results=3, max_tokens=1)
    assert out.count == 1 and any("max_tokens" in w for w in out.warnings)
    other = digest(
        parse("search_fast_max_tokens_per_page.json"), (), max_results=3, max_tokens=None
    )
    assert not any("max_tokens" in w for w in other.warnings)


def test_the_default_count_warning_says_the_query_may_have_had_few_hits():
    four = response(*[item(url=f"https://e.example/{i}") for i in range(4)])
    out = digest(four, (), max_tokens=1)
    (warning,) = out.warnings
    assert "max_tokens" in warning and "few hits" in warning
    assert digest(four, ()).warnings == []
    assert "few hits" not in digest(four, (), max_results=10, max_tokens=1).warnings[0]


def test_only_the_configured_key_is_replaced_in_a_snippet():
    snippet = f"key {KEY} model pplx-embed-v1-0.6b example {EXAMPLE}"
    out = digest(response(item(snippet=snippet)), (KEY,))
    assert out.results[0].snippet == f"key [redacted] model pplx-embed-v1-0.6b example {EXAMPLE}"


def test_the_configured_key_in_dates_title_and_url_is_replaced():
    out = digest(
        response(
            item(
                title=f"t {KEY}",
                url=f"https://e.example/{KEY}",
                date=KEY,
                last_updated=f"u {KEY}",
            )
        ),
        (KEY,),
    )
    got = out.results[0]
    assert KEY not in got.model_dump_json()
    assert got.date == "[redacted]" and got.last_updated == "u [redacted]"


def test_oversized_fields_are_cut_with_one_warning_each_count():
    out = digest(response(item(snippet="y" * 30000)), ())
    assert len(out.results[0].snippet) == 20000
    assert out.warnings == ["1 field cut to this server's size cap."]
    out = digest(response(item(last_updated="d" * 100)), ())
    assert len(out.results[0].last_updated) == 64 and len(out.warnings) == 1
    assert digest(parse("search_fast_single.json"), ()).warnings == []


def test_a_key_shaped_request_id_is_removed_and_cut_and_a_non_string_one_is_none():
    out = digest(response(item(), id=f"id-{EXAMPLE}-" + "z" * 300), ())
    assert EXAMPLE not in (out.request_id or "") and len(out.request_id or "") <= 128
    assert digest(response(item(), id=12345), ()).request_id is None


def test_items_without_a_usable_url_are_dropped_with_one_warning():
    out = digest(response(item(), {"title": "no url"}, item(url=None), "stray", item(url="")), ())
    assert out.count == 1 and out.warnings == [
        "4 results dropped: not an object or without a usable url."
    ]


def test_null_and_non_text_fields_keep_the_result_without_raising():
    out = digest(response({"title": None, "url": "https://e.example", "snippet": 5, "date": 7}), ())
    (got,) = out.results
    assert (got.title, got.snippet, got.date) == ("", "", None) and out.warnings == []

"""Task 1.1 (py-search-api): ``SearchResponse`` is tolerant of every recorded Search body."""

import json

import pytest
from fixture_support import FIXTURE_DIR
from pydantic import ValidationError

from mcp_perplexity_pro.models import SearchResponse


def ok_fixtures():
    out = []
    for path in sorted(FIXTURE_DIR.glob("search_*.json")):
        if path.name.endswith(".meta.json") or path.name.endswith(("_400.json", "_401.json")):
            continue
        out.append(path)
    return out


def test_there_are_twenty_recorded_200_bodies_holding_68_results():
    paths = ok_fixtures()
    assert len(paths) == 20
    assert sum(len(json.loads(p.read_text())["results"]) for p in paths) == 68
    for path in paths:  # the sidecar agrees that every one is a 200
        meta = json.loads(path.with_suffix(".meta.json").read_text())
        assert meta["http_status"] == 200, path.name


@pytest.mark.parametrize("path", ok_fixtures(), ids=lambda p: p.stem)
def test_every_recorded_200_parses_with_its_results_count(path):
    body = json.loads(path.read_text())
    parsed = SearchResponse.model_validate(body)
    assert len(parsed.results) == len(body["results"])
    assert parsed.id == body["id"]


def test_a_result_without_a_date_is_kept_as_received():
    body = {"id": "x", "results": [{"title": "t", "url": "u", "last_updated": "2026-01-01"}]}
    (item,) = SearchResponse.model_validate(body).results
    assert "date" not in item and item["last_updated"] == "2026-01-01"


def test_extra_top_level_fields_and_result_fields_are_kept():
    body = {
        "id": "x",
        "server_time": 1.5,
        "usage": {"cost": {"total_cost": 0.5}},
        "results": [{"title": "t", "url": "u", "extra": {"a": 1}}],
    }
    parsed = SearchResponse.model_validate(body)
    assert parsed.model_dump()["server_time"] == 1.5
    assert parsed.model_dump()["usage"] == {"cost": {"total_cost": 0.5}}
    assert parsed.results[0]["extra"] == {"a": 1}


def test_a_null_title_a_numeric_date_and_a_string_item_parse_and_are_kept():
    body = {"id": "x", "results": [{"title": None, "url": "u", "date": 20260101}, "stray"]}
    parsed = SearchResponse.model_validate(body)
    assert parsed.results == body["results"]


@pytest.mark.parametrize("name", ["search_whitespace_query_empty", "search_fast_date_range_empty"])
def test_empty_recorded_bodies_parse_to_zero_results_with_an_id(name):
    parsed = SearchResponse.model_validate(json.loads((FIXTURE_DIR / f"{name}.json").read_text()))
    assert parsed.results == [] and parsed.id


@pytest.mark.parametrize("body", [{"id": "x"}, {"id": "x", "results": {"a": 1}}])
def test_a_missing_or_non_list_results_is_rejected(body):
    with pytest.raises(ValidationError):
        SearchResponse.model_validate(body)


def test_a_body_without_an_id_parses_with_none():
    assert SearchResponse.model_validate({"results": []}).id is None

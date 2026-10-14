"""py-agent-citation-fixes: every cited result id reaches ``sources`` and structured answers
lose their trailing citation markers (spec ``agent-ask`` "Sources" and "Structured output")."""

import json
import re
import time

import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro import agent
from mcp_perplexity_pro.agent import Source, digest, source_line, strip_trailing_markers
from mcp_perplexity_pro.models import AgentRun
from mcp_perplexity_pro.routing import Route


def run_of(name):
    return AgentRun.model_validate(json.loads((FIXTURE_DIR / f"{name}.json").read_text()))


def inline(output, **extra):
    return AgentRun.model_validate(
        {"id": "resp_x", "status": "completed", "output": output, **extra}
    )


def message(text):
    return {"type": "message", "content": [{"type": "output_text", "text": text}]}


# --- Sources keep every id --------------------------------------------------------------------


def test_a_url_seen_under_several_ids_keeps_all_of_them():
    d = digest(run_of("agent_background_cancelled"))
    by_url = {s.url: s for s in d.sources}
    assert by_url["https://crates.io/crates/rs-stats"].ids == [10, 71]
    assert by_url["https://crates.io/crates/rs-stats"].id == 10
    assert by_url["https://crates.io/crates/scirs2-stats"].ids == [9, 68]
    assert len({s.url for s in d.sources}) == len(d.sources)  # each URL still once


def test_every_marker_the_completed_research_cites_has_a_source():
    run = run_of("agent_background_completed")
    d = digest(run)
    cited = {int(n) for n in re.findall(r"\[web:(\d+)\]", d.answer)}
    assert cited == {1, 11, 21}
    known = {i for s in d.sources for i in s.ids}
    assert cited <= known


def test_fetch_only_run_has_no_ids():
    d = digest(run_of("agent_low_fetch_url"))
    assert d.sources and all(s.ids == [] and s.id is None for s in d.sources)


def test_fetched_page_first_then_search_row_for_the_same_url():
    output = [
        {"type": "fetch_url_results", "contents": [{"url": "https://a.test/", "title": "Fetched"}]},
        {
            "type": "search_results",
            "results": [
                {"id": 7, "url": "https://a.test/", "title": "Searched", "date": "2026-01-01"}
            ],
        },
    ]
    (only,) = digest(inline(output)).sources
    assert only.title == "Fetched" and only.date is None  # the first row's fields stay
    assert only.ids == [7] and only.id == 7


def test_ids_ignore_booleans_and_non_integers_and_repeat_ids():
    output = [
        {
            "type": "search_results",
            "results": [
                {"id": True, "url": "https://b.test/"},
                {"id": "3", "url": "https://b.test/"},
                {"id": 4, "url": "https://b.test/"},
                {"id": 4, "url": "https://b.test/"},
            ],
        }
    ]
    (only,) = digest(inline(output)).sources
    assert only.ids == [4] and only.id == 4


def test_a_source_stored_before_this_change_still_reads():
    old = Source(**{"url": "https://c.test/", "title": "t", "date": None, "id": 5})
    assert old.ids == [] and old.id == 5


# --- The readable result shows the ids --------------------------------------------------------


def test_source_line_shows_ids_and_is_unchanged_without_them():
    assert source_line(1, Source(url="https://d.test/", title="T", ids=[10, 71], id=10)) == (
        "1. T - https://d.test/ (ids 10, 71)"
    )
    assert source_line(2, Source(url="https://d.test/", title=None)) == "2. https://d.test/"


# --- Marker cleaner -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "cleaned", "count"),
    [
        ("Acme Corp [1][3]", "Acme Corp", 2),
        ("Acme Corp[1]", "Acme Corp", 1),
        ("Acme [web:12]", "Acme", 1),
        ("Acme [1] [web:0]  ", "Acme", 2),
        ("[1][2]", "", 2),
        ("see [2] for details", "see [2] for details", 0),
        ("see [2024]", "see [2024]", 0),
        ("a[1,2]", "a[1,2]", 0),
        ("[0]", "[0]", 0),
        ("x [01]", "x [01]", 0),
        ("[٣]", "[٣]", 0),  # Arabic-Indic digit is not a marker
        ("Acme [1]", "Acme ", 1),  # no-break space is not ASCII whitespace; kept
        ("[fetch:3]", "[fetch:3]", 0),
        ("plain", "plain", 0),
        ("", "", 0),
    ],
)
def test_strip_trailing_markers(text, cleaned, count):
    assert strip_trailing_markers(text) == (cleaned, count)


def test_the_cleaner_runs_in_linear_time():
    spaces = " " * 500_000 + "x"
    markers = "[1]" * 500_000
    start = time.perf_counter()
    assert strip_trailing_markers(spaces) == (spaces, 0)
    assert strip_trailing_markers(markers) == ("", 500_000)
    assert strip_trailing_markers("a" + " " * 500_000 + "[1]") == ("a", 1)
    assert time.perf_counter() - start < 1.0


def structured(value_json: str):
    return digest(inline([message(value_json)]), structured=True)


def test_structured_answer_loses_trailing_markers_and_warns_once():
    raw = '{"name":"Acme Corp [1][3]","note":"see [2] for details","n":2050000,"k[1]":"v"}'
    d = structured(raw)
    assert d.answer == raw  # the raw text is untouched
    assert d.answer_json == {
        "name": "Acme Corp",
        "note": "see [2] for details",
        "n": 2050000,
        "k[1]": "v",
    }
    assert d.warnings == [
        "Removed 2 citation marker(s) from string values of answer_json; the answer text is "
        "unchanged."
    ]


def test_nested_values_are_cleaned_and_counted_in_one_warning():
    d = structured('{"rows":[{"co":"Acme [web:12]"},{"co":"Bolt"},"x [4]"]}')
    assert d.answer_json == {"rows": [{"co": "Acme"}, {"co": "Bolt"}, "x"]}
    assert len(d.warnings) == 1 and "Removed 2 citation" in d.warnings[0]


def test_clean_structured_answer_has_no_warning():
    d = structured('{"city":"Paris","population":2050000}')
    assert d.answer_json == {"city": "Paris", "population": 2050000} and d.warnings == []


def nested(depth: int) -> str:
    return '{"a":' * depth + '"deep [1]"' + "}" * depth


def test_a_value_at_the_depth_limit_is_cleaned():
    d = structured(nested(agent.MAX_JSON_DEPTH))
    node = d.answer_json
    for _ in range(agent.MAX_JSON_DEPTH - 1):
        node = node["a"]
    assert node == {"a": "deep"}


@pytest.mark.parametrize("depth", [agent.MAX_JSON_DEPTH + 1, 900, 5000])
def test_a_value_nested_beyond_the_limit_keeps_the_billed_answer_and_serialises(depth):
    """pydantic cannot serialise ~400 levels; the digest must hand back something it can."""
    d = structured(nested(depth))
    assert d.answer_json is None and d.answer.startswith('{"a":')
    assert any("nested deeper than" in w for w in d.warnings)
    d.model_dump(mode="json")  # must not raise


def test_a_failing_cleaner_keeps_the_answer_and_warns(monkeypatch):
    def boom(value):
        raise RuntimeError("boom")

    monkeypatch.setattr(agent, "clean_markers", boom)
    d = structured('{"name":"Acme [1]"}')
    assert d.answer_json == {"name": "Acme [1]"}
    assert any("cleaning was skipped" in w for w in d.warnings)
    assert d.status == "completed" and d.answer == '{"name":"Acme [1]"}'


def test_markers_are_not_removed_when_no_schema_was_sent():
    d = digest(inline([message("Acme [1]")]))
    assert d.answer == "Acme [1]" and d.answer_json is None and d.warnings == []


def test_a_failure_part_way_through_leaves_the_value_uncleaned(monkeypatch):
    real = agent.strip_trailing_markers
    calls = {"n": 0}

    def flaky(text):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(text)

    monkeypatch.setattr(agent, "strip_trailing_markers", flaky)
    d = structured('{"a":"x [1]","b":"y [2]"}')
    assert d.answer_json == {"a": "x [1]", "b": "y [2]"}
    assert any("cleaning was skipped" in w for w in d.warnings)


# --- bounded ids ---------------------------------------------------------------------------------


def test_one_url_under_many_ids_is_bounded_and_fast():
    rows = [{"id": i, "url": "https://e.test/"} for i in range(1, 200_001)]
    start = time.perf_counter()
    d = digest(inline([{"type": "search_results", "results": rows}]))
    assert time.perf_counter() - start < 2.0
    (only,) = d.sources
    assert only.ids == list(range(1, agent.MAX_IDS_PER_SOURCE + 1)) and only.id == 1
    assert any("result id(s) were dropped" in w for w in d.warnings)


# --- the readable results ----------------------------------------------------------------------


def test_ask_render_shows_ids_beside_each_source():
    from mcp_perplexity_pro.tools.ask import build_result, render_answer

    d = digest(run_of("agent_background_cancelled"))
    text = render_answer(
        build_result(
            d,
            route=Route("standard", None, "perplexity/sonar", None, "default"),
            latency_ms=1,
            project="default",
        )
    )
    assert "https://crates.io/crates/rs-stats (ids 10, 71)" in text


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (
            '[{"url": "https://o.test/", "title": "Old", "date": null, "id": 5}]',
            "1. Old - https://o.test/",
        ),
        (
            '[{"url": "https://n.test/", "title": "New", "date": null, "id": 10, "ids": [10, 71]}]',
            "1. New - https://n.test/ (ids 10, 71)",
        ),
    ],
)
async def test_jobs_result_renders_stored_sources_old_and_new(research_world, stored, expected):
    from research_support import seed_job

    w = await research_world()
    jid = await seed_job(
        w, status="completed", usage_recorded=1, result_text="the answer", sources_json=stored
    )
    result = await w.call("perplexity_jobs", action="result", job_id=jid)
    assert not result.is_error
    lines = result.content[0].text.splitlines()
    assert expected in lines
    (src,) = result.structured_content["sources"]
    assert src["ids"] == ([] if "ids" not in stored else [10, 71])

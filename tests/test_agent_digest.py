"""Task 2.2: ``agent.digest`` and the upstream-text cleaner (design D3, D14)."""

import json

import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.agent import (
    clean_error_text,
    clean_reason,
    clean_status,
    digest,
)
from mcp_perplexity_pro.models import AgentRun

KEY = "test-dummy-api-key"
TOKEN = "pplx-" + "Qq7_" * 12


def load(name):
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


def run_of(name):
    return AgentRun.model_validate(load(name))


def inline(output, **extra):
    return AgentRun.model_validate(
        {"id": "resp_x", "status": "completed", "output": output, **extra}
    )


def message(text):
    return {"type": "message", "content": [{"type": "output_text", "text": text}]}


def search(*urls, **extra):
    return {
        "type": "search_results",
        "results": [{"url": u, "title": f"t-{u}", **extra} for u in urls],
    }


def final_text(raw):
    return [i for i in raw["output"] if i["type"] == "message"][-1]["content"][-1]["text"]


def test_filtered_fast_answer_sources_and_inline_markers_are_unchanged():
    raw = load("agent_fast_filters")
    d = digest(run_of("agent_fast_filters"))
    assert d.answer == final_text(raw)
    results = [r for i in raw["output"] if i["type"] == "search_results" for r in i["results"]]
    assert [s.url for s in d.sources] == [r["url"] for r in results]  # in order
    assert len(set(s.url for s in d.sources)) == len(d.sources)
    first = d.sources[0]
    assert (first.title, first.date, first.id) == (
        results[0]["title"],
        results[0]["date"],
        results[0]["id"],
    )
    assert (d.status, d.incomplete_reason, d.warnings) == ("completed", None, [])
    assert d.model == "openai/gpt-6-luna"


def test_the_fetched_page_is_a_source_with_no_id():
    raw = load("agent_low_fetch_url")
    d = digest(run_of("agent_low_fetch_url"))
    page = [c for i in raw["output"] if i["type"] == "fetch_url_results" for c in i["contents"]]
    assert [(s.url, s.title, s.id) for s in d.sources] == [(page[0]["url"], page[0]["title"], None)]
    assert d.sources[0].date is None


def test_the_incomplete_run_is_a_result_with_a_warning_and_its_real_cost():
    d = digest(run_of("agent_incomplete_truncated"))
    assert (d.status, d.incomplete_reason, d.answer) == ("incomplete", "max_output_tokens", "")
    assert len(d.warnings) == 1 and "cut short" in d.warnings[0]
    assert "max_output_tokens" in d.warnings[0]
    assert (d.usage.cost_usd, d.usage.cost_source) == ("0.00001", "reported")


def test_structured_answer_parses_and_reports_exact_cost_and_tokens():
    d = digest(run_of("agent_structured_output"), structured=True)
    assert d.answer == '{"city":"Paris","population":2050000}'
    assert d.answer_json == {"city": "Paris", "population": 2050000}
    assert d.warnings == []
    assert (d.usage.cost_usd, d.usage.cost_source) == ("0.00147", "reported")
    assert (d.usage.input_tokens, d.usage.output_tokens, d.usage.total_tokens) == (3660, 18, 3678)


def test_answer_json_is_absent_unless_a_schema_was_asked_for():
    assert digest(run_of("agent_structured_output")).answer_json is None


def test_the_ungrounded_model_run_has_no_sources():
    d = digest(run_of("agent_model_without_tools"))
    assert d.sources == [] and d.answer.startswith("I can")


def test_cost_is_null_when_unreported():
    d = digest(inline([message("hi")]))
    assert (d.usage.cost_usd, d.usage.cost_source, d.usage.total_tokens) == (None, "none", None)


def test_a_repeated_url_appears_once_at_its_first_position():
    run = inline([search("https://a", "https://b"), search("https://a", "https://c"), message("x")])
    assert [s.url for s in digest(run).sources] == ["https://a", "https://b", "https://c"]


def test_a_url_repeated_between_search_and_fetch_is_one_source():
    fetch = {"type": "fetch_url_results", "contents": [{"url": "https://a", "title": "fetched"}]}
    sources = digest(inline([search("https://a"), fetch, message("x")])).sources
    assert [(s.url, s.title) for s in sources] == [("https://a", "t-https://a")]


def test_non_json_text_for_a_schema_is_null_with_a_warning_and_the_text_is_kept():
    d = digest(inline([message("Paris, probably")]), structured=True)
    assert d.answer == "Paris, probably" and d.answer_json is None
    assert len(d.warnings) == 1 and "JSON" in d.warnings[0]


@pytest.mark.parametrize("text", ["NaN", "Infinity", "[1, 2", "{'a': 1}", "{" * 100000])
def test_unusable_json_texts_are_null_not_errors(text):
    d = digest(inline([message(text)]), structured=True)
    assert d.answer_json is None and d.answer == text


@pytest.mark.parametrize(
    "output",
    [
        {"type": "message", "content": [{"type": "output_text", "text": "x"}]},
        "just text",
        None,
        7,
        [None, 3, "x", {"type": "message"}],
        [{"type": "message", "content": None}],
        [{"type": "message", "content": [None, {"type": "output_text", "text": 5}]}],
        [{"type": "search_results", "results": "nope"}, {"type": "fetch_url_results"}],
        [{"type": "search_results", "results": [None, {"url": 5}, {"title": "no url"}]}],
    ],
)
def test_malformed_bodies_give_an_empty_answer_and_never_raise(output):
    d = digest(inline(output))
    assert d.answer == "" and d.sources == []


def test_a_malformed_usage_and_incomplete_details_never_raise():
    d = digest(inline([message("ok")], usage="oops", incomplete_details=["x"]))
    assert d.answer == "ok" and d.usage.cost_source == "none" and d.incomplete_reason is None


def test_the_last_message_item_and_its_last_text_part_win():
    first, last = message("one"), message("two")
    last["content"].insert(0, {"type": "output_text", "text": "part"})
    assert digest(inline([first, last])).answer == "two"
    assert digest(inline([message("keep"), {"type": "message"}])).answer == ""


# --- redaction and caps of upstream text (D14) ----------------------------------------------


def test_a_status_with_a_key_shaped_token_is_redacted_then_cut_to_64():
    run = inline([message("x")])
    run.status = f"weird {TOKEN} " + "s" * 200
    shown = digest(run, secrets=(KEY,)).status
    assert TOKEN not in shown and "pplx-" not in shown and len(shown) <= 64


def test_the_configured_key_in_a_status_is_removed():
    assert KEY not in clean_status(f"x {KEY} y", (KEY,))


def test_redaction_precedes_the_cut_so_a_straddling_key_leaves_no_fragment():
    text = "a" * 60 + TOKEN
    shown = clean_status(text, ())
    assert "pplx" not in shown and len(shown) <= 64
    shown = clean_status("b" * 60 + KEY, (KEY,))
    assert "test-d" not in shown  # not even the start of the key survives the cut


def test_error_text_is_redacted_and_cut_to_2000():
    shown = clean_error_text({"message": f"boom {TOKEN} {KEY} " + "e" * 5000, "code": 1}, (KEY,))
    assert TOKEN not in shown and KEY not in shown and len(shown) <= 2000


def test_error_text_accepts_a_plain_string_and_nothing():
    assert clean_error_text("plain", ()) == "plain"
    assert clean_error_text(None, ()) == ""
    assert clean_error_text({"no": "message"}, ()) != ""  # a non-empty description, never a crash


def test_reason_is_cut_to_200_and_redacted():
    run = inline(
        [message("x")], status="incomplete", incomplete_details={"reason": f"{TOKEN}" + "r" * 400}
    )
    d = digest(run, secrets=(KEY,))
    assert d.incomplete_reason is not None and len(d.incomplete_reason) <= 200
    assert "pplx-" not in d.incomplete_reason and "pplx-" not in "".join(d.warnings)
    assert len(clean_reason("r" * 500, ())) == 200


def test_a_key_shaped_example_inside_the_answer_and_sources_is_left_as_received():
    run = inline(
        [
            search("https://x/" + TOKEN),
            message(f"Use {TOKEN} as an example, never a real key."),
        ]
    )
    d = digest(run, secrets=(KEY,))
    assert TOKEN in d.answer
    assert d.sources[0].url == "https://x/" + TOKEN and TOKEN in d.sources[0].title

"""routing_evidence: the loader, the lazy holder, the score rules and the class mean
(routing-v2 task 2.1; the scenarios of the routing-evidence spec)."""

import json
import logging
from decimal import Decimal

import pytest
from evidence_support import TODAY, document, dumps, evidence, figure

from mcp_perplexity_pro import routing_evidence as ev


def write(tmp_path, doc):
    path = tmp_path / ev.FILENAME
    path.write_text(doc if isinstance(doc, str) else dumps(doc))
    return path


def invalid(doc):
    with pytest.raises(ValueError):
        ev.parse(dumps(doc), TODAY)


# --- the packaged file ------------------------------------------------------------------------


def test_the_packaged_evidence_is_valid_with_an_entry_for_every_shortlist_id_and_the_fallback():
    packaged = ev.load_packaged(TODAY)
    assert packaged.version == 1 and len(packaged.shortlist) == 8
    assert set(packaged.shortlist) <= set(packaged.models)
    assert packaged.fallbacks["default"].model in packaged.models
    assert set(packaged.task_classes) == {"coding", "reasoning", "browsing"}


def test_the_shipped_state_has_empty_scores_so_no_model_is_eligible_for_any_class():
    packaged = ev.load_packaged(TODAY)
    assert all(not entry.scores for entry in packaged.models.values())
    assert not packaged.has_verified_score()
    assert all(
        packaged.class_score(m, c) is None
        for m in packaged.shortlist
        for c in packaged.task_classes
    )


def test_no_file_in_the_data_directory_uses_the_packaged_evidence_without_a_warning(tmp_path):
    loaded = ev.load(tmp_path / ev.FILENAME, TODAY)
    assert (loaded.origin, loaded.state, loaded.warning) == ("packaged", "missing", None)


# --- override, corrupt, newer -----------------------------------------------------------------


def test_a_valid_data_directory_file_wins_and_is_never_modified(tmp_path):
    doc = document(shortlist=["x/one", "x/two"], fallback="x/one")
    path = write(tmp_path, doc)
    before = path.read_bytes()
    loaded = ev.load(path, TODAY)
    assert loaded.origin == "file" and loaded.evidence.shortlist == ["x/one", "x/two"]
    assert path.read_bytes() == before and sorted(p.name for p in tmp_path.iterdir()) == [
        ev.FILENAME
    ]


def test_a_corrupt_file_falls_back_with_one_warning_and_is_left_as_it_was(tmp_path):
    path = write(tmp_path, "this is not json {")
    loaded = ev.load(path, TODAY)
    assert loaded.origin == "packaged" and loaded.state == "corrupt"
    assert str(path) in (loaded.warning or "")
    assert path.read_text() == "this is not json {"


def test_a_newer_version_falls_back_with_a_warning(tmp_path):
    loaded = ev.load(write(tmp_path, document(version=2)), TODAY)
    assert (loaded.origin, loaded.state) == ("packaged", "newer") and loaded.warning


def test_a_directory_in_place_of_the_file_is_unreadable_not_a_crash(tmp_path):
    (tmp_path / ev.FILENAME).mkdir()
    loaded = ev.load(tmp_path / ev.FILENAME, TODAY)
    assert (loaded.origin, loaded.state) == ("packaged", "unreadable")


def test_a_fallback_model_with_no_entry_is_invalid_and_replaced(tmp_path):
    doc = document()
    del doc["models"]["a/cheap"]
    loaded = ev.load(write(tmp_path, doc), TODAY)
    assert (loaded.origin, loaded.state) == ("packaged", "invalid")
    assert "a/cheap" in (loaded.warning or "")


def test_a_shortlist_id_with_no_entry_is_invalid():
    doc = document()
    del doc["models"]["c/top"]
    invalid(doc)


# --- lazy holder ------------------------------------------------------------------------------


def test_the_holder_reads_nothing_until_the_first_snapshot_and_warns_once(tmp_path, caplog):
    state = ev.EvidenceState(tmp_path, today=lambda: TODAY)
    path = write(tmp_path, "garbage")
    with caplog.at_level(logging.WARNING, logger=ev.logger.name):
        first = state.snapshot()
        second = state.snapshot()
    assert first is second and first.state == "corrupt"
    assert len([r for r in caplog.records if "routing evidence" in r.getMessage()]) == 1
    assert path.read_text() == "garbage"


def test_building_the_holder_touches_no_file(tmp_path):
    missing = tmp_path / "never-created"
    ev.EvidenceState(missing)
    assert not missing.exists()


# --- scores -----------------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["source_url", "as_of", "basis", "harness", "verified_at"])
def test_a_figure_missing_any_field_is_invalid(missing):
    bad = figure()
    del bad[missing]
    invalid(document(scores={"b/mid": {"b1": bad}}))


def test_an_unsourced_figure_is_invalid_and_the_warning_names_model_and_benchmark(tmp_path):
    bad = figure()
    del bad["source_url"]
    loaded = ev.load(write(tmp_path, document(scores={"b/mid": {"b1": bad}})), TODAY)
    assert loaded.state == "invalid"
    assert "b/mid" in loaded.warning and "b1" in loaded.warning


@pytest.mark.parametrize("score", [101, -1, True, "80", None])
def test_a_score_outside_0_to_100_or_not_a_number_is_invalid(score):
    invalid(document(scores={"b/mid": {"b1": figure(score)}}))


@pytest.mark.parametrize(
    "url", ["http://v.example/x", "v.example/x", "ftp://v.example", "https://"]
)
def test_a_source_url_must_be_https(url):
    invalid(document(scores={"b/mid": {"b1": figure(source_url=url)}}))


@pytest.mark.parametrize(
    "url",
    [
        "https://llm-stats.com/models/x",
        "https://www.llm-stats.com/benchmarks",
        "https://API.LLM-STATS.COM/stats/v1",
    ],
)
def test_a_source_url_on_the_llm_stats_host_is_rejected(url):
    invalid(document(scores={"b/mid": {"b1": figure(source_url=url)}}))


def test_a_lookalike_host_is_not_rejected():
    evidence(scores={"b/mid": {"b1": figure(source_url="https://notllm-stats.com/x")}})


def test_verified_before_it_was_recorded_or_in_the_future_is_invalid():
    invalid(document(scores={"b/mid": {"b1": figure(as_of="2026-10-20", verified="2026-10-10")}}))
    invalid(document(scores={"b/mid": {"b1": figure(verified="2026-11-12")}}))


def test_verified_on_the_load_date_and_on_as_of_are_valid():
    evidence(
        scores={"b/mid": {"b1": figure(verified="2026-11-11"), "b2": figure(verified="2026-11-01")}}
    )


def test_a_null_verified_at_is_kept_but_ignored_by_selection():
    e = evidence(scores={"b/mid": {"b3": figure(90, verified=None)}})
    assert "b3" in e.models["b/mid"].scores
    assert e.class_score("b/mid", "browsing") is None and not e.has_verified_score()


# --- classes ----------------------------------------------------------------------------------


def test_a_class_with_an_empty_benchmark_list_is_invalid():
    invalid(document(classes={"coding": ["b1"], "reasoning": []}))


def test_a_class_listing_an_unknown_benchmark_is_invalid():
    doc = document()
    doc["task_classes"]["coding"]["benchmarks"].append("terminal_bench_9")
    invalid(doc)


def test_a_different_benchmark_version_id_does_not_count():
    doc = document(
        classes={"coding": ["terminal_bench_2_1"]},
        scores={"b/mid": {"terminal_bench_4_0": figure(70)}},
    )
    doc["benchmarks"]["terminal_bench_2_1"] = {"name": "Terminal-Bench"}
    doc["benchmarks"]["terminal_bench_4_0"] = {"name": "Terminal-Bench"}  # same name, other id
    e = ev.parse(dumps(doc), TODAY)
    assert e.class_score("b/mid", "coding") is None


def test_a_class_absent_from_task_classes_scores_nothing():
    e = evidence(scores={"b/mid": {"b3": figure(70)}})
    assert e.class_score("b/mid", "reasoning") is None


# --- class mean -------------------------------------------------------------------------------


def test_the_class_score_is_the_exact_mean_of_the_listed_benchmarks():
    e = evidence(scores={"b/mid": {"b1": figure(60), "b2": figure(70)}})
    assert e.class_score("b/mid", "coding") == Decimal(65)


def test_a_missing_benchmark_makes_the_model_ineligible_for_that_class_only():
    e = evidence(scores={"b/mid": {"b1": figure(60), "b3": figure(50)}})
    assert e.class_score("b/mid", "coding") is None
    assert e.class_score("b/mid", "browsing") == Decimal(50)


def test_scores_keep_their_json_text_as_decimal_so_80_3_is_exact():
    e = ev.parse(
        json.dumps(document(scores={"b/mid": {"b3": figure(0)}})).replace(
            '"score": 0,', '"score": 80.3,'
        ),
        TODAY,
    )
    assert e.class_score("b/mid", "browsing") == Decimal("80.3")
    assert e.class_score("b/mid", "browsing") - 3 == Decimal("77.3")


def test_editing_the_class_in_the_file_changes_membership_with_no_code():
    scores = {"b/mid": {"b1": figure(60), "b2": figure(70)}}
    before = evidence(scores=scores, classes={"coding": ["b1", "b2"], "reasoning": ["b3"]})
    after = evidence(scores=scores, classes={"coding": ["b1"], "reasoning": ["b2", "b3"]})
    assert before.class_score("b/mid", "coding") == Decimal(65)
    assert after.class_score("b/mid", "coding") == Decimal(60)
    assert after.class_score("b/mid", "reasoning") is None

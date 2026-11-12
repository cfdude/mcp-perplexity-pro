"""The offline coverage gate (routing-v2 task 2.6): which classes the evaluation scores."""

from decimal import Decimal

import pytest
from evidence_support import evidence, figure, matrix_of, row
from routing_eval import coverage as cov
from routing_eval import promptset

IDS = ["a/one", "b/two", "c/three", "d/four"]


def ev_with(scores_by_class, classes=None):
    """Evidence where ``scores_by_class`` maps a class to ``{model: score}``."""
    bench = {"coding": ["b1", "b2"], "browsing": ["b3"]}
    scores: dict = {}
    for cls, by_model in scores_by_class.items():
        for model_id, score in by_model.items():
            for b in bench[cls]:
                scores.setdefault(model_id, {})[b] = figure(score)
    return evidence(scores=scores, shortlist=IDS, fallback="a/one", classes=classes)


MATRIX = matrix_of({m: row() for m in IDS})


def prompts(**counts):
    out = []
    for cls, n in counts.items():
        out += [{"task": cls, "expected": "standard", "id": f"{cls}{i}"} for i in range(n)]
    return out


def by_class(coverage):
    return {c.task_class: c for c in coverage.classes}


def test_a_class_with_three_eligible_models_and_full_router_share_is_kept():
    e = ev_with({"coding": {"a/one": 70, "b/two": 71, "c/three": 72}})
    c = cov.compute(e, MATRIX, prompts(coding=4))
    assert by_class(c)["coding"].kept and c.kept == ("coding",)
    assert by_class(c)["coding"].share == 1 and by_class(c)["coding"].eligible == (
        "a/one",
        "b/two",
        "c/three",
    )


def test_two_eligible_models_drop_the_class_from_the_kept_list():
    # mutation of the gate: one model fewer than the kept class had
    e = ev_with({"coding": {"a/one": 70, "b/two": 71}})
    c = cov.compute(e, MATRIX, prompts(coding=4))
    assert not by_class(c)["coding"].kept and c.kept == () and c.excluded[0] == "browsing"


def test_a_removed_model_is_not_eligible_so_three_become_two():
    e = ev_with({"coding": {"a/one": 70, "b/two": 71, "c/three": 72}})
    gone = matrix_of({**{m: row() for m in IDS}, "c/three": row(status="removed")})
    assert not by_class(cov.compute(e, gone, prompts(coding=4)))["coding"].kept


@pytest.mark.parametrize(("chosen", "total", "kept"), [(3, 4, True), (2, 3, False), (15, 20, True)])
def test_the_share_threshold_is_75_percent_inclusive(chosen, total, kept):
    c = cov.ClassCoverage("coding", ("a", "b", "c"), total, chosen)
    assert c.kept is kept


def test_a_class_absent_from_the_evidence_falls_back_for_every_prompt():
    e = ev_with(
        {"coding": {"a/one": 70, "b/two": 71, "c/three": 72}}, classes={"coding": ["b1", "b2"]}
    )
    c = by_class(cov.compute(e, MATRIX, prompts(browsing=3, coding=2)))
    assert c["browsing"].eligible == () and c["browsing"].router_chosen == 0
    assert not c["browsing"].kept and c["coding"].kept


def test_fewer_than_two_kept_classes_record_the_thin_outcome():
    e = ev_with({"coding": {"a/one": 70, "b/two": 71, "c/three": 72}})
    c = cov.compute(e, MATRIX, prompts(coding=4, browsing=4))
    assert c.outcome == cov.THIN == "evidence too thin: router cannot be evaluated"
    both = ev_with(
        {
            "coding": {"a/one": 70, "b/two": 71, "c/three": 72},
            "browsing": {"a/one": 50, "b/two": 51, "d/four": 52},
        }
    )
    assert cov.compute(both, MATRIX, prompts(coding=4, browsing=4)).outcome == cov.PASSED


def test_the_file_round_trips_through_kept_classes_and_the_harness_refusal(tmp_path):
    e = ev_with({"coding": {"a/one": 70, "b/two": 71, "c/three": 72}})
    thin = cov.compute(e, MATRIX, prompts(coding=4, browsing=4))
    path = tmp_path / "coverage.md"
    path.write_text(cov.render(thin))
    assert cov.kept_classes(path) == ("coding",)
    with pytest.raises(RuntimeError, match="coverage gate failed"):
        cov.assert_passed(path)
    both = ev_with(
        {
            "coding": {"a/one": 70, "b/two": 71, "c/three": 72},
            "browsing": {"a/one": 50, "b/two": 51, "d/four": 52},
        }
    )
    path.write_text(cov.render(cov.compute(both, MATRIX, prompts(coding=4, browsing=4))))
    assert cov.kept_classes(path) == ("browsing", "coding")
    cov.assert_passed(path)  # does not raise


def test_a_missing_file_also_refuses_the_harness(tmp_path):
    with pytest.raises(RuntimeError, match="does not exist"):
        cov.assert_passed(tmp_path / "nope.md")


def test_no_kept_class_reads_as_an_empty_list(tmp_path):
    path = tmp_path / "coverage.md"
    path.write_text(cov.render(cov.compute(ev_with({}), MATRIX, prompts(coding=2))))
    assert cov.kept_classes(path) == ()


def test_the_committed_file_is_exactly_what_the_generator_writes_now(tmp_path):
    fresh = tmp_path / "coverage.md"
    cov.generate(fresh)
    assert cov.COVERAGE_PATH.read_text() == fresh.read_text()  # generated, never hand-written


def test_the_committed_kept_list_names_only_classes_of_the_set():
    assert set(cov.kept_classes()) <= set(promptset.CLASSES)
    assert Decimal(cov.MIN_SHARE) == Decimal("0.75") and cov.MIN_MODELS == 3 and cov.MIN_KEPT == 2

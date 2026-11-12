"""routing_select.select: eligibility, the class mean, the decimal margin, contenders, the blended
price, ties, the effort clip, the fallback chain, the preset rung, media kinds and the search
rule (routing-v2 task 4.1; the routing-evidence scenarios). Every case builds small in-memory
matrices and evidence literals: nothing is read from a file."""

import subprocess
import sys
from decimal import Decimal

import pytest
from evidence_support import figure, matrix_of, row

from mcp_perplexity_pro import routing_select as rs
from mcp_perplexity_pro.errors import PerplexityError

IDS = ["a/cheap", "b/mid", "c/top"]


def ev(browsing=None, coding=None, shortlist=None, fallback="a/cheap", **kw):
    """Evidence where each argument maps a model id to its class score (verified)."""
    from evidence_support import evidence

    scores = {}
    for cls, bench in ((browsing, ["b3"]), (coding, ["b1", "b2"])):
        for model_id, score in (cls or {}).items():
            for b in bench:
                scores.setdefault(model_id, {})[b] = figure(score)
    return evidence(scores=scores, shortlist=shortlist, fallback=fallback, **kw)


def mx(prices=None, **rows):
    base = {m: row(prices.get(m, (1.0, 1.0)) if prices else (1.0, 1.0)) for m in IDS}
    base.update(rows)
    return matrix_of(base)


def pick(evidence, matrix, *, cls="browsing", tier="standard", margin=3, **kw):
    return rs.select(cls, tier, "ask", evidence, matrix, kw.pop("kinds", ()), margin, **kw)


# --- margin, contenders, price ----------------------------------------------------------------


def test_the_cheaper_model_within_the_margin_wins():
    e = ev(browsing={"a/cheap": 78, "c/top": 80})
    m = mx({"a/cheap": (0.5, 1.5), "c/top": (5, 10)})  # blended 1.0 against 6.25
    s = pick(e, m, margin=3)
    assert (s.model, s.selected_by) == ("a/cheap", "router")


def test_a_model_outside_the_margin_loses_even_when_cheaper():
    e = ev(browsing={"a/cheap": 76, "c/top": 80})
    m = mx({"a/cheap": (0.5, 1.5), "c/top": (5, 10)})
    assert pick(e, m, margin=3).model == "c/top"


# 64.1 - 3 is 61.099999999999994 in floats, so only exact decimals keep 61.1 a contender
@pytest.mark.parametrize(
    ("best", "other"), [("80", "77"), ("80.3", "77.3"), ("64.1", "61.1"), ("73.7", "70.7")]
)
def test_the_margin_boundary_is_inclusive_in_exact_decimal(best, other):
    e = ev(browsing={"a/cheap": Decimal(other), "c/top": Decimal(best)})
    m = mx({"a/cheap": (0.1, 0.1), "c/top": (9, 9)})
    assert pick(e, m, margin=3).model == "a/cheap"


def test_a_boundary_that_floats_get_wrong_is_still_a_contender_in_decimal():
    # float: 60.1 - 0.3 = 59.800000000000004 > 59.8, so a float comparison drops the model
    e = ev(browsing={"a/cheap": Decimal("59.8"), "c/top": Decimal("60.1")})
    m = mx({"a/cheap": (0.1, 0.1), "c/top": (9, 9)})
    assert pick(e, m, margin="0.3").model == "a/cheap"
    assert pick(e, m, margin=0.3).model == "a/cheap"


def test_the_80_3_case_is_a_contender_with_float_input_for_the_margin_too():
    e = ev(browsing={"a/cheap": Decimal("77.3"), "c/top": Decimal("80.3")})
    m = mx({"a/cheap": (0.1, 0.1), "c/top": (9, 9)})
    assert pick(e, m, margin=3.0).model == "a/cheap"
    assert pick(e, m, margin=Decimal("3.0")).model == "a/cheap"
    assert pick(e, m, margin="3").model == "a/cheap"


def test_one_hundredth_beyond_the_boundary_is_not_a_contender():
    e = ev(browsing={"a/cheap": Decimal("77.29"), "c/top": Decimal("80.3")})
    m = mx({"a/cheap": (0.1, 0.1), "c/top": (9, 9)})
    assert pick(e, m, margin=3).model == "c/top"


def test_margin_zero_means_the_best_score_always_wins():
    e = ev(browsing={"a/cheap": Decimal("79.5"), "c/top": 80})
    m = mx({"a/cheap": (0.1, 0.1), "c/top": (9, 9)})
    assert pick(e, m, margin=0).model == "c/top"


def test_the_blend_weights_the_input_price_three_to_one():
    assert rs.blended_price(2, 10) == Decimal("4")  # (3 * 2 + 10) / 4
    assert rs.blended_price(0.1, 0.5) == Decimal("0.2")
    # price the output only (the mutation) would pick the other model here
    e = ev(browsing={"a/cheap": 80, "b/mid": 80})
    m = mx({"a/cheap": (1.0, 9.0), "b/mid": (2.0, 3.0)})  # blended 3.0 against 2.25
    assert pick(e, m).model == "b/mid"
    m2 = mx({"a/cheap": (3.0, 1.0), "b/mid": (1.0, 2.0)})  # input-heavy: 2.5 against 1.25
    assert pick(e, m2).model == "b/mid"


def test_a_full_tie_goes_to_the_higher_score_then_the_smaller_id_whatever_the_shortlist_order():
    same = {"a/cheap": 80, "b/mid": 80}
    m = mx()
    for order in (["a/cheap", "b/mid", "c/top"], ["c/top", "b/mid", "a/cheap"]):
        assert pick(ev(browsing=same, shortlist=order), m).model == "a/cheap"
    higher = {"a/cheap": 79, "b/mid": 80}
    assert pick(ev(browsing=higher), m).model == "b/mid"


def test_the_winner_is_the_same_whatever_the_dict_order_of_the_matrix():
    e = ev(browsing={"a/cheap": 80, "b/mid": 80, "c/top": 80})
    forward = mx()
    backward = matrix_of(dict(reversed(list(forward.models.items()))))
    assert pick(e, forward) == pick(e, backward)


def test_an_unknown_price_is_not_eligible_and_is_never_chosen():
    e = ev(browsing={"a/cheap": 70, "c/top": 95})
    m = mx(**{"c/top": row((1.0, None))})
    assert pick(e, m, margin=3).model == "a/cheap"
    m = mx(**{"c/top": row((None, 1.0))})
    assert pick(e, m, margin=3).model == "a/cheap"


# --- eligibility, one condition at a time -----------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    ["off_shortlist", "removed", "absent_from_matrix", "unpriced", "no_score", "unverified"],
)
def test_each_condition_excludes_a_model_on_its_own(mutate):
    scores = {"a/cheap": 60, "c/top": 90}
    shortlist = None
    m = mx()
    if mutate == "off_shortlist":
        shortlist = ["a/cheap", "b/mid"]
        e = ev(browsing=scores, shortlist=shortlist)
    elif mutate == "no_score":
        e = ev(browsing={"a/cheap": 60})
    elif mutate == "unverified":
        from evidence_support import evidence

        e = evidence(
            scores={
                "a/cheap": {"b3": figure(60)},
                "c/top": {"b3": figure(90, verified=None)},
            }
        )
    else:
        e = ev(browsing=scores)
    if mutate == "removed":
        m = mx(**{"c/top": row(status="removed")})
    if mutate == "absent_from_matrix":
        m = matrix_of({k: v for k, v in mx().models.items() if k != "c/top"})
    if mutate == "unpriced":
        m = mx(**{"c/top": row((None, None))})
    assert pick(e, m, margin=3).model == "a/cheap"


def test_a_model_needs_a_verified_score_for_every_benchmark_of_the_class():
    from evidence_support import evidence

    e = evidence(
        scores={
            "a/cheap": {"b1": figure(80), "b2": figure(80)},
            "c/top": {"b1": figure(99)},  # b2 missing: not eligible for coding
        },
    )
    s = rs.select("coding", "standard", "ask", e, mx())
    assert s.model == "a/cheap"


def test_the_class_score_is_the_mean_of_its_benchmarks():
    from evidence_support import evidence

    e = evidence(
        scores={
            "a/cheap": {"b1": figure(60), "b2": figure(70)},  # mean 65
            "c/top": {"b1": figure(70), "b2": figure(70)},  # mean 70, outside a margin of 3
        },
    )
    m = mx({"a/cheap": (0.1, 0.1), "c/top": (9, 9)})
    assert rs.select("coding", "standard", "ask", e, m).model == "c/top"
    assert rs.select("coding", "standard", "ask", e, m, margin=5).model == "a/cheap"


# --- catalog changes (built from small matrices, no edit needed) ------------------------------


def test_a_removed_winner_gives_way_to_the_next_contender_then_to_the_fallback():
    e = ev(browsing={"a/cheap": 79, "b/mid": 80, "c/top": 70})
    m = mx({"a/cheap": (1, 1), "b/mid": (2, 2)})
    assert pick(e, m).model == "a/cheap"
    gone = mx({"a/cheap": (1, 1), "b/mid": (2, 2)}, **{"a/cheap": row(status="removed")})
    assert pick(e, gone).model == "b/mid"
    none_left = matrix_of({m_: row(status="removed") for m_ in IDS if m_ != "x"} | {"x/y": row()})
    s = pick(e, none_left)
    assert s.selected_by == "fallback" and s.preset == "low"


def test_a_price_rise_changes_the_winner():
    e = ev(browsing={"a/cheap": 80, "b/mid": 80})
    assert pick(e, mx({"a/cheap": (1, 1), "b/mid": (2, 2)})).model == "a/cheap"
    assert pick(e, mx({"a/cheap": (3, 3), "b/mid": (2, 2)})).model == "b/mid"


def test_a_model_listed_in_the_matrix_but_off_the_shortlist_is_never_chosen():
    e = ev(browsing={"a/cheap": 70})
    m = mx(**{"z/new": row((0.01, 0.01))})
    assert pick(e, m).model == "a/cheap"


# --- effort -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "accepted", "expected"),
    [
        ("standard", ALL := ["minimal", "low", "medium", "high", "xhigh", "max"], "medium"),
        ("complex", ALL, "medium"),
        ("light", ALL, "low"),
        ("standard", ["high", "xhigh"], "high"),
        ("standard", ["minimal", "high"], "minimal"),
        ("light", ["medium", "high"], "medium"),
        ("standard", [], None),
        ("standard", "unprobed", None),
    ],
)
def test_the_effort_is_the_highest_accepted_not_above_the_target_else_the_lowest_else_none(
    tier, accepted, expected
):
    e = ev(browsing={"a/cheap": 80})
    m = mx(**{"a/cheap": row(efforts=accepted)})
    assert pick(e, m, tier=tier).effort == expected


def test_a_complex_prompt_never_gets_more_than_medium_and_the_tier_does_not_pick_the_model():
    e = ev(browsing={"a/cheap": 80, "b/mid": 80})
    m = mx({"a/cheap": (3, 3), "b/mid": (1, 1)})
    light, complex_ = pick(e, m, tier="light"), pick(e, m, tier="complex")
    assert light.model == complex_.model == "b/mid"
    assert (light.effort, complex_.effort) == ("low", "medium")


def test_a_model_the_matrix_does_not_know_gets_no_effort():
    assert rs.clip_effort([], "medium") is None
    assert rs.clip_effort(["low"], "high") == "low"
    assert rs.clip_effort(["xhigh"], "low") == "xhigh"
    assert rs.clip_effort(["xhigh"], "low", lowest_fallback=False) is None


# --- the fallback chain -----------------------------------------------------------------------


def test_no_eligible_model_runs_the_default_fallback_model_at_low():
    e = ev(browsing={"b/mid": 70})
    m = mx(**{"b/mid": row(status="removed")})
    s = pick(e, m)
    assert (s.model, s.effort, s.selected_by, s.preset) == ("a/cheap", "low", "fallback", None)
    assert "browsing" in s.reason and "fallback default model" in s.reason


def test_the_fallback_model_at_low_is_clipped_never_raised():
    e = ev()
    m = mx(**{"a/cheap": row(efforts=["medium", "high"])})
    assert pick(e, m).effort is None  # nothing at or below low: no reasoning at all
    m = mx(**{"a/cheap": row(efforts=["minimal", "high"])})
    assert pick(e, m).effort == "minimal"


def test_a_removed_fallback_model_falls_to_the_documented_preset_of_the_tier():
    e = ev()
    m = mx(**{"a/cheap": row(status="removed")})
    for tier, preset in (("light", "fast"), ("standard", "low"), ("complex", "medium")):
        s = pick(e, m, tier=tier)
        assert (s.model, s.effort, s.preset, s.selected_by) == (None, None, preset, "fallback")


def test_unverified_evidence_means_every_nameless_call_falls_back():
    s = pick(ev(), mx())
    assert s.selected_by == "fallback" and s.model == "a/cheap"


def test_a_class_absent_from_the_evidence_falls_back_naming_the_class():
    s = rs.select("reasoning", "standard", "ask", ev(browsing={"b/mid": 90}), mx())
    assert s.selected_by == "fallback" and "reasoning" in s.reason


def test_search_false_with_no_model_rung_fails_naming_search_and_sends_nothing():
    m = mx(**{"a/cheap": row(status="removed")})
    with pytest.raises(PerplexityError) as info:
        pick(ev(), m, search=False)
    assert info.value.category == "invalid_request"
    assert "search" in str(info.value) and "preset always searches" in str(info.value)


def test_search_false_is_fine_when_a_model_rung_exists():
    s = pick(ev(), mx(), search=False)
    assert s.model == "a/cheap" and s.selected_by == "fallback"
    assert pick(ev(browsing={"b/mid": 80}), mx(), search=False).model == "b/mid"


# --- media kinds (the stubs answer yes, no and unknown) ---------------------------------------


def stub(answers):
    def accepts(model_id, kinds):
        return answers.get(model_id, "unknown")

    return accepts


def test_an_empty_set_excludes_nobody_even_with_a_stub_that_says_no():
    e = ev(browsing={"b/mid": 80})
    assert pick(e, mx(), accepts=stub({})).model == "b/mid"


def test_only_a_yes_is_eligible_and_unknown_is_never_substituted():
    e = ev(browsing={"a/cheap": 80, "b/mid": 80, "c/top": 82})
    m = mx({"a/cheap": (0.1, 0.1), "b/mid": (1, 1), "c/top": (9, 9)})
    only_mid = stub({"a/cheap": "unknown", "b/mid": "yes", "c/top": "no"})
    assert pick(e, m, kinds={"image"}, accepts=only_mid).model == "b/mid"
    all_yes = stub({"a/cheap": "yes", "b/mid": "yes", "c/top": "yes"})
    assert pick(e, m, kinds={"image"}, accepts=all_yes).model == "a/cheap"


def test_the_fallback_model_is_checked_the_same_way():
    e = ev()
    for answer in ("no", "unknown"):
        with pytest.raises(PerplexityError) as info:
            pick(
                e,
                mx(),
                kinds={"image"},
                accepts=stub({"a/cheap": answer}),
                preset_accepts=lambda p, k: "unknown",
            )
        assert "image" in str(info.value)
    s = pick(e, mx(), kinds={"image"}, accepts=stub({"a/cheap": "yes"}))
    assert s.model == "a/cheap"


@pytest.mark.parametrize(("answer", "ok"), [("yes", True), ("no", False), ("unknown", False)])
def test_the_preset_rung_with_media_needs_a_yes_from_preset_accepts(answer, ok):
    m = mx(**{"a/cheap": row(status="removed")})
    call = lambda: pick(  # noqa: E731
        ev(), m, kinds={"image"}, accepts=stub({}), preset_accepts=lambda p, k: answer
    )
    if ok:
        assert call().preset == "low"
    else:
        with pytest.raises(PerplexityError) as info:
            call()
        assert info.value.category == "invalid_request" and "image" in str(info.value)


def test_nothing_accepts_a_document_names_the_kind():
    with pytest.raises(PerplexityError) as info:
        pick(ev(browsing={"b/mid": 80}), mx(), kinds={"document", "image"}, accepts=stub({}))
    assert "document and image" in str(info.value)


def test_a_search_false_media_call_with_no_model_names_both():
    with pytest.raises(PerplexityError) as info:
        pick(ev(), mx(), kinds={"image"}, search=False, accepts=stub({}))
    text = str(info.value)
    assert "image" in text and "search" in text


def test_the_real_matrix_answers_decide_when_no_stub_is_given():
    e = ev(browsing={"a/cheap": 80, "b/mid": 80})
    m = mx(**{"a/cheap": row(refused_inputs=("image",)), "b/mid": row(inputs=("image",))})
    assert pick(e, m, kinds={"image"}).model == "b/mid"
    assert pick(e, m).model == "a/cheap"  # no kinds: modality excludes nobody


# --- reason and purity ------------------------------------------------------------------------


def test_the_reason_names_class_contenders_and_rule_and_never_exceeds_120_ascii():
    e = ev(browsing={"a/cheap": 79, "b/mid": 80})
    s = pick(e, mx())
    assert s.reason == "browsing; 2 within 3 pts; cheapest"
    single = pick(ev(browsing={"b/mid": 80}), mx())
    assert single.reason == "browsing; 1 within 3 pts; best score"
    odd = rs._class_label("codingé hunter2" + "x" * 500)
    assert odd == "unknown" and len(rs._reason("x" * 400)) == 120 and rs._reason("é").isascii()


def test_select_never_mutates_its_inputs_and_is_repeatable():
    e, m = ev(browsing={"a/cheap": 79, "b/mid": 80}), mx()
    before = (e.model_dump_json(), m.model_dump_json())
    assert pick(e, m) == pick(e, m)
    assert (e.model_dump_json(), m.model_dump_json()) == before


def test_bad_arguments_are_a_programming_error():
    with pytest.raises(ValueError):
        rs.select("browsing", "standard", "research", ev(), mx())
    with pytest.raises(ValueError):
        rs.select("browsing", "huge", "ask", ev(), mx())


def test_the_choice_is_the_same_under_hash_seeds_0_and_1():
    code = (
        "import sys; sys.path.insert(0, 'tests')\n"
        "from evidence_support import evidence, figure, matrix_of, row\n"
        "from mcp_perplexity_pro import routing_select as rs\n"
        "ids = ['a/x', 'b/x', 'c/x', 'd/x', 'e/x', 'f/x']\n"
        "scores = {i: {'b3': figure(80)} for i in ids}\n"
        "e = evidence(scores=scores, shortlist=ids, fallback='a/x')\n"
        "m = matrix_of({i: row((1.0, 1.0)) for i in ids})\n"
        "s = rs.select('browsing', 'standard', 'ask', e, m)\n"
        "print(s.model, s.effort, s.reason)\n"
    )
    outputs = []
    for seed in ("0", "1"):
        env = {"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"}
        done = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
        )
        outputs.append(done.stdout)
    assert outputs[0] == outputs[1] and outputs[0].startswith("a/x medium")

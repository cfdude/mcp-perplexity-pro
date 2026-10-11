"""Task 3.1 (py-decisions-tool): ``decisions.digest`` and the output models."""

import json

from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.decisions import DecideOutput, digest
from mcp_perplexity_pro.models import DecisionsResponse

KEY = "pplx-" + "Zk3Hq8Lm2Vx9Rt5Wy7Nb4Jd6Fc1Sg0A"


def load(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def parse(name):
    return DecisionsResponse.model_validate(load(name))


def response(answers, **extra):
    return DecisionsResponse.model_validate({"answers": answers, **extra})


def test_the_three_question_body_keeps_its_typed_answers_in_the_callers_order():
    raw = load("decisions_three_questions.json")
    out = digest(
        parse("decisions_three_questions.json"),
        (KEY,),
        question_names=["severity", "urgent", "area"],
    )
    assert isinstance(out, DecideOutput) and list(out.answers) == ["severity", "urgent", "area"]
    assert out.answers["urgent"].noul == raw["answers"]["urgent"]["noul"]
    area = out.answers["area"]
    assert area.choice == "export" and set(area.probabilities) == {"export", "auth", "billing"}
    severity = out.answers["severity"]
    assert severity.score == raw["answers"]["severity"]["score"]
    assert severity.legend == {"0": "minor", "1": "moderate", "2": "major", "3": "critical"}
    assert (out.model, out.input_tokens, out.output_tokens) == ("pplx-decider-v1.1-27b", 347, 3)
    assert out.warnings == []


def test_choice_and_score_fixtures_fill_their_fields_and_leave_others_null():
    choice = digest(parse("decisions_choice.json"), (), question_names=["category"]).answers[
        "category"
    ]
    assert choice.type == "choice" and choice.noul is None and choice.score is None
    assert choice.confidence is not None and choice.legend is None
    score = digest(parse("decisions_score.json"), (), question_names=["satisfaction"]).answers[
        "satisfaction"
    ]
    assert score.type == "score" and score.choice is None and score.legend and score.probabilities


def test_missing_string_and_unknown_type_answers_are_left_out_with_a_warning_each():
    body = response({"a": {"type": "noul", "noul": 0.5}, "c": "stray", "d": {"type": "rank"}})
    out = digest(body, (), question_names=["a", "b", "c", "d"])
    assert list(out.answers) == ["a"]
    assert [w.split("'")[1] for w in out.warnings] == ["b", "c", "d"]


def test_nan_and_string_numbers_become_null():
    body = response(
        {
            "q": {
                "type": "choice",
                "choice": "x",
                "confidence": float("nan"),
                "probabilities": {"x": "high", "y": True},
            }
        }
    )
    answer = digest(body, (), question_names=["q"]).answers["q"]
    assert answer.confidence is None and answer.probabilities == {"x": None, "y": None}


def test_only_the_configured_key_is_replaced_in_option_strings():
    body = response(
        {
            "q": {
                "type": "choice",
                "choice": f"{KEY} pplx-decider-v1.1-27b",
                "confidence": 1,
                "probabilities": {f"k {KEY}": 1},
            }
        }
    )
    answer = digest(body, (KEY,), question_names=["q"]).answers["q"]
    assert answer.choice == "[redacted] pplx-decider-v1.1-27b"
    assert list(answer.probabilities) == ["k [redacted]"]


def test_a_long_option_is_cut_to_500():
    answer = digest(
        response({"q": {"type": "choice", "choice": "y" * 600}}), (), question_names=["q"]
    ).answers["q"]
    assert len(answer.choice) == 500


def test_unreadable_usage_gives_null_token_counts_and_partial_usage_is_kept():
    for usage in (
        None,
        {"input_tokens": True},
        {"input_tokens": -1},
        {"input_tokens": 1.5},
        {"input_tokens": "5"},
    ):
        out = digest(
            response({"q": {"type": "noul", "noul": 0.1}}, usage=usage), (), question_names=["q"]
        )
        assert out.input_tokens is None and out.output_tokens is None, usage
    out = digest(
        response({"q": {"type": "noul", "noul": 0.1}}, usage={"input_tokens": 9}),
        (),
        question_names=["q"],
    )
    assert (out.input_tokens, out.output_tokens) == (9, None)


def test_digest_does_not_raise_when_every_answer_value_is_none():
    out = digest(response({"q": None}), (), question_names=["q"])
    assert out.answers == {} and len(out.warnings) == 1

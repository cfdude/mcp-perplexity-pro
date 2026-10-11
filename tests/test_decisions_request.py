"""Task 2.1 (py-decisions-tool): ``decisions.build_request`` against the recorded requests."""

import json
import re
from pathlib import Path

import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.decisions import DecideOptions, build_request
from mcp_perplexity_pro.errors import PerplexityError

SRC = Path(__file__).resolve().parent.parent / "src" / "mcp_perplexity_pro"
COMPARED = [
    "decisions_noul",
    "decisions_choice",
    "decisions_score",
    "decisions_three_questions",
    "decisions_model_v1",
    "decisions_11_questions",
    "decisions_32_questions",
]
REFUSED_ALTHOUGH_ACCEPTED = {"decisions_empty_state": "blank state"}


def sidecar(name):
    return json.loads((FIXTURE_DIR / f"{name}.meta.json").read_text())


def options_from(request):
    return DecideOptions(
        state=request["state"], questions=request["questions"], model=request["model"]
    )


@pytest.mark.parametrize("name", COMPARED)
def test_a_recorded_request_is_rebuilt_exactly(name):
    request = sidecar(name)["request"]
    assert build_request(options_from(request)) == request


def test_every_recorded_200_request_is_compared_or_accounted_for():
    ok = {
        p.name.removesuffix(".meta.json")
        for p in FIXTURE_DIR.glob("decisions_*.meta.json")
        if json.loads(p.read_text())["http_status"] == 200
    }
    assert ok == set(COMPARED) | set(REFUSED_ALTHOUGH_ACCEPTED)


def test_the_blank_state_request_the_api_accepted_is_refused():
    request = sidecar("decisions_empty_state")["request"]
    with pytest.raises(PerplexityError) as caught:
        build_request(options_from(request))
    assert str(caught.value).startswith("state")


def test_the_default_model_is_sent_and_only_the_three_keys():
    request = build_request(
        DecideOptions(state="s", questions={"q": {"type": "noul", "instructions": "y"}})
    )
    assert set(request) == {"model", "state", "questions"}
    assert request["model"] == "pplx-decider-v1.1-27b"


def test_thirty_two_questions_are_accepted_and_a_deep_copy_is_sent():
    questions = {f"q{i}": {"type": "noul", "instructions": "a"} for i in range(32)}
    request = build_request(DecideOptions(state={"a": [1]}, questions=questions))
    assert len(request["questions"]) == 32
    assert request["questions"] is not questions


NOUL = {"type": "noul", "instructions": "y"}
CHOICE = {"type": "choice", "criteria": {"a": "x", "b": None}}
SCORE = {"type": "score", "criteria": ["low", "high"]}

REFUSALS = [
    ("state", dict(state="")),
    ("state", dict(state="   ")),
    ("state", dict(state={})),
    ("state", dict(state=[])),
    ("state", dict(state=5)),
    ("state", dict(state="x" * 200_001)),
    ("state", dict(state=[{"type": "image_url", "image_url": {"url": "x"}}])),
    ("state", dict(state={"a": "data:image/png;base64,AAAA"})),
    ("model", dict(model="pplx-decider-nope")),
    ("questions", dict(questions={})),
    ("questions", dict(questions=None)),
    ("questions", dict(questions={f"q{i}": NOUL for i in range(33)})),
    ("questions", dict(questions={"  ": NOUL})),
    ("questions", dict(questions={"n" * 129: NOUL})),
    ("questions[q]", dict(questions={"q": "noul"})),
    ("questions[q]", dict(questions={"q": {"type": "rank", "criteria": ["a"]}})),
    ("questions[q]", dict(questions={"q": {**NOUL, "extra": 1}})),
    ("questions[q]", dict(questions={"q": {"type": "noul"}})),
    ("questions[q]", dict(questions={"q": {"type": "noul", "criteria": {"maybe": "x"}}})),
    ("questions[q]", dict(questions={"q": {"type": "noul", "instructions": 5}})),
    ("questions[q]", dict(questions={"q": {"type": "noul", "instructions": "  "}})),
    ("questions[q]", dict(questions={"q": {"type": "choice", "criteria": {}}})),
    ("questions[q]", dict(questions={"q": {"type": "choice", "criteria": ["a"]}})),
    (
        "questions[q]",
        dict(questions={"q": {"type": "choice", "criteria": {f"o{i}": "x" for i in range(256)}}}),
    ),
    ("questions[q]", dict(questions={"q": {"type": "score", "criteria": []}})),
    ("questions[q]", dict(questions={"q": {"type": "score", "criteria": list("abcdefghijk")}})),
    ("questions[q]", dict(questions={"q": {"type": "score", "criteria": {"0": "a"}}})),
]


@pytest.mark.parametrize(("option", "kwargs"), REFUSALS, ids=lambda v: str(v)[:50])
def test_a_bad_input_is_invalid_request_naming_the_option(option, kwargs):
    kwargs = {"state": "s", "questions": {"q": NOUL}, **kwargs}
    with pytest.raises(PerplexityError) as caught:
        build_request(DecideOptions(**kwargs))
    assert caught.value.category == "invalid_request"
    assert str(caught.value).startswith(option)


def test_good_choice_and_score_shapes_are_accepted():
    request = build_request(DecideOptions(state="s", questions={"c": CHOICE, "s": SCORE}))
    assert request["questions"] == {"c": CHOICE, "s": SCORE}


def test_the_validators_are_imported_from_agent_not_copied():
    text = (SRC / "decisions.py").read_text()
    assert not re.search(r"def (_bad|_int_in|check_text)\b", text)

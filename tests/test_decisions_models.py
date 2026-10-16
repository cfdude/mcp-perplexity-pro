"""Task 1.1 (py-decisions-tool): ``DecisionsResponse`` is tolerant of every recorded 200 body."""

import json

import pytest
from fixture_support import FIXTURE_DIR
from pydantic import ValidationError

from mcp_perplexity_pro.models import DecisionsResponse


def ok_fixtures():
    return [
        p
        for p in sorted(FIXTURE_DIR.glob("decisions_*.json"))
        if not p.name.endswith((".meta.json", "_400.json", "_401.json"))
    ]


def test_there_are_eleven_recorded_200_bodies():
    paths = ok_fixtures()
    assert len(paths) == 11  # eight probes plus three decisions_tier_*
    for path in paths:
        assert json.loads(path.with_suffix(".meta.json").read_text())["http_status"] == 200


@pytest.mark.parametrize("path", ok_fixtures(), ids=lambda p: p.stem)
def test_every_recorded_200_parses_with_its_answers(path):
    body = json.loads(path.read_text())
    parsed = DecisionsResponse.model_validate(body)
    assert list(parsed.answers) == list(body["answers"])
    assert parsed.model == body["model"] and parsed.usage == body["usage"]


def test_extra_fields_are_kept():
    body = {"model": "m", "extra": 1, "answers": {"q": {"type": "noul", "noul": 0.5, "x": 2}}}
    parsed = DecisionsResponse.model_validate(body)
    assert parsed.model_dump()["extra"] == 1 and parsed.answers["q"]["x"] == 2


def test_odd_values_are_kept():
    parsed = DecisionsResponse.model_validate({"answers": {"q": "stray"}, "usage": None})
    assert parsed.answers == {"q": "stray"} and parsed.usage is None


@pytest.mark.parametrize("body", [{"model": "x"}, {"answers": [1]}])
def test_missing_or_non_object_answers_is_rejected(body):
    with pytest.raises(ValidationError):
        DecisionsResponse.model_validate(body)

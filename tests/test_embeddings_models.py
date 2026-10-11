"""Task 1.1 (py-embeddings): ``EmbeddingsResponse`` is tolerant of every recorded 200 body."""

import json

import pytest
from fixture_support import FIXTURE_DIR
from pydantic import ValidationError

from mcp_perplexity_pro.models import EmbeddingsResponse


def ok_fixtures():
    """Fixtures whose SIDECAR says 200 (``embeddings_dim_odd_06b`` is a 400 without a suffix)."""
    return [
        p.with_name(p.name.removesuffix(".meta.json") + ".json")
        for p in sorted(FIXTURE_DIR.glob("embeddings_*.meta.json"))
        if json.loads(p.read_text())["http_status"] == 200
    ]


def test_there_are_nine_recorded_200_bodies():
    assert len(ok_fixtures()) == 9


@pytest.mark.parametrize("path", ok_fixtures(), ids=lambda p: p.stem)
def test_every_recorded_200_parses_with_its_data(path):
    body = json.loads(path.read_text())
    parsed = EmbeddingsResponse.model_validate(body)
    assert len(parsed.data) == len(body["data"])
    assert parsed.model == body["model"] and parsed.usage == body["usage"]


def test_extra_fields_are_kept():
    body = {"data": [{"embedding": "AA==", "index": 0, "x": 1}], "extra": 2, "model": "m"}
    parsed = EmbeddingsResponse.model_validate(body)
    assert parsed.model_dump()["extra"] == 2 and parsed.data[0]["x"] == 1


@pytest.mark.parametrize("body", [{"model": "x"}, {"data": {"a": 1}}])
def test_missing_or_non_list_data_is_rejected(body):
    with pytest.raises(ValidationError):
        EmbeddingsResponse.model_validate(body)

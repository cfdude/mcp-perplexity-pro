"""Task 4.1 (py-embeddings): ``embeddings.build_request`` against the recorded requests."""

import json

import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.embeddings import build_request
from mcp_perplexity_pro.errors import PerplexityError

M6, M4 = "pplx-embed-v1-0.6b", "pplx-embed-v1-4b"
ENCODING = {"base64_int8": "int8", "base64_binary": "binary"}
COMPARED = [
    "embeddings_single_06b",
    "embeddings_two_4b_dim256",
    "embeddings_binary_06b",
    "embeddings_int8_explicit_06b",
    "embeddings_4b_default_dims",
    "embeddings_unicode_06b",
]
BATCH_SHAPES = ["embeddings_64_inputs_4000_chars", "embeddings_100_inputs_5000_chars"]
NEVER_SENT = ["embeddings_unknown_field_accepted"]  # an unknown field is not expressible


def sidecar(name):
    return json.loads((FIXTURE_DIR / f"{name}.meta.json").read_text())


@pytest.mark.parametrize("name", COMPARED)
def test_a_recorded_request_is_rebuilt_with_the_deliberate_differences_only(name):
    request = sidecar(name)["request"]
    inputs = request["input"] if isinstance(request["input"], list) else [request["input"]]
    built = build_request(
        request["model"],
        inputs,
        dimensions=request.get("dimensions"),
        encoding=ENCODING[request.get("encoding_format", "base64_int8")],
    )
    expected = {**request, "input": inputs}  # a one-string input is sent as a one-element list
    expected.setdefault("encoding_format", "base64_int8")  # the tool always names the encoding
    assert built == expected
    assert set(built) - set(request) <= {"encoding_format"}


def test_the_default_size_request_sends_no_dimensions_and_always_the_model_and_encoding():
    built = build_request(M6, ["hello world"])
    assert built == {"model": M6, "input": ["hello world"], "encoding_format": "base64_int8"}
    assert "dimensions" not in build_request(M4, ["x"])  # mutation: a default would show here


def test_the_large_request_fixtures_are_batch_shapes():
    metas = {n: sidecar(n)["request"] for n in BATCH_SHAPES}
    assert all(m["_large_request"] for m in metas.values())
    # the recorded 64 x 4000-character batch (256000 characters) is over OUR character budget
    # (100000): the planner would send it as three requests; 25 x 4000 and 64 short texts pass
    assert len(build_request(M6, ["a" * 4000] * 25, dimensions=128)["input"]) == 25
    assert len(build_request(M6, ["b" * 100] * 64, dimensions=128)["input"]) == 64
    with pytest.raises(PerplexityError) as caught:
        build_request(M6, ["a"] * 100)  # the 100-input fixture's shape exceeds our 64 cap
    assert str(caught.value).startswith("input")


def test_every_recorded_200_request_is_compared_or_accounted_for():
    ok = {
        p.name.removesuffix(".meta.json")
        for p in FIXTURE_DIR.glob("embeddings_*.meta.json")
        if json.loads(p.read_text())["http_status"] == 200
    }
    assert ok == set(COMPARED) | set(BATCH_SHAPES) | set(NEVER_SENT)


REFUSALS = [
    ("model", dict(model="nope")),
    ("dimensions", dict(dimensions=64)),
    ("dimensions", dict(dimensions=130)),
    ("dimensions", dict(dimensions=2000)),  # above the 0.6b maximum
    ("dimensions", dict(model=M4, dimensions=2561)),
    ("dimensions", dict(dimensions=True)),
    ("dimensions", dict(dimensions=256.0)),
    ("encoding", dict(encoding="float")),
    ("input", dict(inputs=[])),
    ("input", dict(inputs=["a"] * 65)),
    ("input", dict(inputs=["a", ""])),
    ("input", dict(inputs=["x" * 4001])),
    ("input", dict(inputs=[1])),
    ("input", dict(inputs="a string")),
    ("input", dict(inputs=["x" * 4000] * 26)),  # 104000 characters in one request
]


@pytest.mark.parametrize(("option", "kwargs"), REFUSALS, ids=lambda v: str(v)[:40])
def test_a_bad_option_is_invalid_request_naming_the_option(option, kwargs):
    arguments = {"model": M6, "inputs": ["a"], **kwargs}
    model, inputs = arguments.pop("model"), arguments.pop("inputs")
    with pytest.raises(PerplexityError) as caught:
        build_request(model, inputs, **arguments)
    assert caught.value.category == "invalid_request" and str(caught.value).startswith(option)

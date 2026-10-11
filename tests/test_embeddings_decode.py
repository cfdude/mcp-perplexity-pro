"""Task 1.3 (py-embeddings): exact vector decoding of both encodings."""

import base64
import json

import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.embeddings import decode_vector
from mcp_perplexity_pro.errors import PerplexityError

DEFAULT_SIZE = {"pplx-embed-v1-0.6b": 1024, "pplx-embed-v1-4b": 2560}

# (fixture, expected bytes per vector, encoding)
RECORDED = [
    ("embeddings_single_06b", 1024, "int8"),  # the 0.6b default size
    ("embeddings_4b_default_dims", 2560, "int8"),  # the 4b default size
    ("embeddings_two_4b_dim256", 256, "int8"),
    ("embeddings_binary_06b", 32, "binary"),  # 256 dimensions, packed
    ("embeddings_int8_explicit_06b", 128, "int8"),
    ("embeddings_unicode_06b", 128, "int8"),
]


def load(name):
    body = json.loads((FIXTURE_DIR / f"{name}.json").read_text())
    meta = json.loads((FIXTURE_DIR / f"{name}.meta.json").read_text())
    return body, meta["request"]


@pytest.mark.parametrize(("name", "size", "encoding"), RECORDED, ids=[r[0] for r in RECORDED])
def test_recorded_vectors_decode_to_their_sizes_and_the_python_bytes(name, size, encoding):
    body, request = load(name)
    dimensions = request.get("dimensions") or DEFAULT_SIZE[request["model"]]
    for item in body["data"]:
        got = decode_vector(item["embedding"], encoding, dimensions)
        assert len(got) == size and got == base64.b64decode(item["embedding"])


def b64(n):
    return base64.b64encode(bytes(range(n % 256)) + b"\x01" * (n - n % 256)).decode()


@pytest.mark.parametrize(
    ("value", "encoding", "dimensions"),
    [
        (b64(127), "int8", 128),  # one byte short
        (b64(129), "int8", 128),  # one byte over
        ("not base64!!", "int8", 128),
        ("", "int8", 128),
        (None, "int8", 128),
        (b64(16), "binary", 130),  # 130 is not a multiple of 8
        (b64(15), "binary", 128),
        (b64(16), "float", 128),
    ],
)
def test_wrong_length_bad_base64_and_bad_arguments_raise_unexpected_response(
    value, encoding, dimensions
):
    with pytest.raises(PerplexityError) as caught:
        decode_vector(value, encoding, dimensions)
    assert caught.value.category == "unexpected_response"
    if isinstance(value, str) and value:
        assert value not in str(caught.value)  # the vector text never enters a message

"""Embeddings API logic for ``perplexity_embed`` (design D1 to D14).

Pure pieces first (decoding, chunking, request building, planning, scoring), then the cost rule
and the operations that use the store and ``costed.costed_call``. Everything that can fail on a
caller's input raises ``PerplexityError("invalid_request", ...)`` naming the option, so a tool
validates first and nothing is sent, recorded or created for a bad call.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Any

from mcp_perplexity_pro import pricing
from mcp_perplexity_pro.agent import _bad
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.usage import Usage, computed_usage, usage_from_embeddings_response

MODELS = ("pplx-embed-v1-0.6b", "pplx-embed-v1-4b")
DEFAULT_MODEL = MODELS[0]
FULL_DIMENSIONS = {"pplx-embed-v1-0.6b": 1024, "pplx-embed-v1-4b": 2560}  # the API's own maximum
MIN_DIMENSIONS = 128
MAX_BATCH_INPUTS = 64  # our batch cap; the API allows 512
MAX_BATCH_CHARS = 100_000  # keeps a batch under the 120000-token limit even at 1 token per char
MAX_CHUNK_CHARS = 4000  # our chunk size (about 1000 tokens); the API allows 32K tokens per input
MAX_CHUNKS_PER_TEXT = 50  # our cap: a longer text is cut, with a warning
ENCODINGS = ("int8", "binary")
API_ENCODING = {"int8": "base64_int8", "binary": "base64_binary"}


# --- Decoding (design D8) --------------------------------------------------------------------


def _unreadable(why: str) -> PerplexityError:
    # never echoes the vector string: it is data, and could be large
    return PerplexityError("unexpected_response", f"An embedding could not be decoded: {why}.")


def decode_vector(b64: object, encoding: str, dimensions: int) -> bytes:
    """The bytes of one base64 vector, strictly: ``int8`` is exactly ``dimensions`` bytes and
    ``binary`` exactly ``dimensions / 8`` (``dimensions`` a multiple of 8). The bytes come back
    unchanged. Raises ``unexpected_response`` otherwise."""
    if not isinstance(b64, str):
        raise _unreadable("not a string")
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise _unreadable("not valid base64") from None
    if encoding == "int8":
        expected = dimensions
    elif encoding == "binary":
        if dimensions % 8:
            raise _unreadable("binary vectors need a multiple of 8 dimensions")
        expected = dimensions // 8
    else:
        raise _unreadable("unknown encoding")
    if len(raw) != expected or not raw:
        raise _unreadable(f"expected {expected} bytes, got {len(raw)}")
    return raw


# --- Cost (design D10) -----------------------------------------------------------------------


def embeddings_usage(model: object, raw: object) -> Usage:
    """The usage of one embeddings request: the cost the API reports (source ``reported``);
    else the documented price per token of the model (source ``computed``) when the model is
    priced and ``prompt_tokens`` is a valid count; else unknown (source ``none``), never zero.
    A reported cost is never replaced. Never raises."""
    parsed = usage_from_embeddings_response(raw)
    try:
        if parsed.cost_source == "reported":
            return parsed
        tokens = parsed.input_tokens
        nano = (
            pricing.embeddings_cost_nano(model, tokens)
            if tokens is not None and isinstance(model, str)
            else None
        )
        if nano is None:
            return parsed
        facts: dict[str, Any] = {"input_tokens": tokens, "total_tokens": parsed.total_tokens}
        return computed_usage(nano, raw=parsed.raw, **facts)
    except Exception:
        return parsed


# --- Chunking (design D3) --------------------------------------------------------------------


def is_blank(text: object) -> bool:
    """The one rule for "no text": not a string, or only whitespace (``index`` and ``status``)."""
    return not isinstance(text, str) or not text.strip()


def text_hash(chunk: str) -> str:
    return hashlib.sha256(chunk.encode("utf-8")).hexdigest()


def _cut_point(rest: str) -> int:
    """Where to cut ``rest`` (longer than a chunk): the last blank line, else line break, else
    space inside the limit, else the limit itself."""
    for separator in ("\n\n", "\n", " "):
        at = rest.rfind(separator, 0, MAX_CHUNK_CHARS)
        if at > 0:
            return at
    return MAX_CHUNK_CHARS


def chunk_text(text: str) -> tuple[list[str], bool]:
    """Split ``text`` into chunks of at most 4000 characters, stripped, empty ones dropped, at
    most 50 of them. Returns ``(chunks, cut)`` where ``cut`` says text beyond the 50th chunk was
    ignored. Deterministic: the same text always gives the same chunks."""
    chunks: list[str] = []
    rest = text
    while rest.strip():
        if len(rest) <= MAX_CHUNK_CHARS:
            piece, rest = rest, ""
        else:
            at = _cut_point(rest)
            piece, rest = rest[:at], rest[at:]
        piece = piece.strip()
        if piece:
            chunks.append(piece)
        if len(chunks) >= MAX_CHUNKS_PER_TEXT and rest.strip():
            return chunks, True
    return chunks, False


# --- Request building (design D2) ------------------------------------------------------------


def check_options(model: object, dimensions: object, encoding: object) -> None:
    """Validate the options every action shares. Raises ``invalid_request`` naming the option."""
    if model not in MODELS:
        raise _bad("model", f"must be one of {', '.join(MODELS)}.")
    if dimensions is not None:
        top = FULL_DIMENSIONS[str(model)]
        if (
            isinstance(dimensions, bool)
            or not isinstance(dimensions, int)
            or not MIN_DIMENSIONS <= dimensions <= top
            or dimensions % 8
        ):
            raise _bad(
                "dimensions",
                f"must be a whole number from {MIN_DIMENSIONS} to {top} for {model}, "
                "a multiple of 8.",
            )
    if encoding not in ENCODINGS:
        raise _bad("encoding", f"must be one of {', '.join(ENCODINGS)}.")


def stored_dimensions(model: str, dimensions: int | None) -> int:
    """The size actually returned: the given ``dimensions``, else the model's full size."""
    return dimensions if dimensions is not None else FULL_DIMENSIONS[model]


def build_request(
    model: str, inputs: list[str], *, dimensions: int | None = None, encoding: str = "int8"
) -> dict[str, Any]:
    """Validate and build the ``POST /v1/embeddings`` body. Pure: no network, no database.
    ``model`` and ``encoding_format`` are always sent; ``dimensions`` only when given (the
    model's full size applies otherwise). Raises ``invalid_request`` naming the option."""
    check_options(model, dimensions, encoding)
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= MAX_BATCH_INPUTS:
        raise _bad("input", f"must be a list of 1 to {MAX_BATCH_INPUTS} texts.")
    total = 0
    for text in inputs:
        if not isinstance(text, str) or not text:
            raise _bad("input", "every text must be a non-empty string.")
        if len(text) > MAX_CHUNK_CHARS:
            raise _bad("input", f"every text is at most {MAX_CHUNK_CHARS} characters.")
        total += len(text)
    if total > MAX_BATCH_CHARS:
        raise _bad("input", f"a request holds at most {MAX_BATCH_CHARS} characters in all.")
    request: dict[str, Any] = {"model": model, "input": list(inputs)}
    if dimensions is not None:
        request["dimensions"] = dimensions
    request["encoding_format"] = API_ENCODING[encoding]
    return request

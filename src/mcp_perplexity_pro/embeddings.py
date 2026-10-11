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
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.usage import Usage, computed_usage, usage_from_embeddings_response

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

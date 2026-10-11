"""Embeddings API logic for ``perplexity_embed`` (design D1 to D14).

Pure pieces first (decoding, chunking, request building, planning, scoring), then the cost rule
and the operations that use the store and ``costed.costed_call``. Everything that can fail on a
caller's input raises ``PerplexityError("invalid_request", ...)`` naming the option, so a tool
validates first and nothing is sent, recorded or created for a bad call.
"""

from __future__ import annotations

import base64
import binascii

from mcp_perplexity_pro.errors import PerplexityError

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

"""Typed error taxonomy for the Perplexity client.

``PerplexityError`` subclasses FastMCP's ``ToolError`` so FastMCP does not mask it and the
server middleware can attach ``category`` to the tool result (design D6). The category names
are the stable identifiers used by every tool error.
"""

from __future__ import annotations

import json
from typing import Any

from fastmcp.exceptions import ToolError

from mcp_perplexity_pro.redaction import redact_text

CATEGORIES = (
    "invalid_request",
    "authentication",
    "forbidden",
    "not_found",
    "rate_limited",
    "upstream_failure",
    "network_timeout",
    "unexpected_response",
)

# Categories that never come from an HTTP status: raised by local validation, storage and the
# server's own contract. Together with CATEGORIES they are the closed eleven-value vocabulary.
TOOL_CATEGORIES = (
    "confirmation_required",
    "storage_busy",
    "internal_error",
)
ALL_CATEGORIES = CATEGORIES + TOOL_CATEGORIES

_STATUS_CATEGORY = {
    400: "invalid_request",
    422: "invalid_request",
    401: "authentication",
    403: "forbidden",
    404: "not_found",
    429: "rate_limited",
}


class PerplexityError(ToolError):
    """A tool failure in exactly one category (any of ``ALL_CATEGORIES``).

    Raised for upstream API failures (the eight ``CATEGORIES``, usually with ``status``) and for
    local ones such as an invalid project name (``invalid_request``) or a busy database
    (``storage_busy``), which carry no status.

    ``message`` is sanitized on construction (key-shaped tokens and any ``secrets`` removed),
    so no upstream text is stored or returned unredacted.
    """

    def __init__(
        self,
        category: str,
        message: str,
        *,
        status: int | None = None,
        api_type: str | None = None,
        api_code: int | str | None = None,
        secrets: tuple[str, ...] = (),
    ) -> None:
        if category not in ALL_CATEGORIES:
            raise ValueError(f"unknown error category {category!r}")
        super().__init__(redact_text(message, secrets))
        self.category = category
        self.status = status
        self.api_type = redact_text(api_type, secrets) if api_type else None
        self.api_code = redact_text(api_code, secrets) if isinstance(api_code, str) else api_code


def category_for_status(status: int) -> str:
    """Map an HTTP status to a category; anything unlisted is ``unexpected_response``."""
    if status in _STATUS_CATEGORY:
        return _STATUS_CATEGORY[status]
    if 500 <= status <= 599:
        return "upstream_failure"
    return "unexpected_response"


def _parse_error_body(body: str) -> tuple[str | None, str | None, Any]:
    """Return ``(message, type, code)`` from ``{"error": {...}}``; each may be absent."""
    try:
        data = json.loads(body)
    except ValueError:
        return None, None, None
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return None, None, None
    message = error.get("message")
    api_type = error.get("type")
    return (
        message if isinstance(message, str) and message else None,
        api_type if isinstance(api_type, str) and api_type else None,
        error.get("code"),
    )


def error_from_response(
    status: int, body: str, *, secrets: tuple[str, ...] = ()
) -> PerplexityError:
    """Build the error for a non-success HTTP response, mapping by status (never by type)."""
    message, api_type, code = _parse_error_body(body)
    text = message or f"Perplexity API returned HTTP {status}"
    if api_type:
        text = f"{text} (type: {api_type})"
    return PerplexityError(
        category_for_status(status),
        text,
        status=status,
        api_type=api_type,
        api_code=code if isinstance(code, int | str) else None,
        secrets=secrets,
    )

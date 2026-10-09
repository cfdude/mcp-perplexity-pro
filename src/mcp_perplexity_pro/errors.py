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

_STATUS_CATEGORY = {
    400: "invalid_request",
    422: "invalid_request",
    401: "authentication",
    403: "forbidden",
    404: "not_found",
    429: "rate_limited",
}


class PerplexityError(ToolError):
    """A failure talking to the Perplexity API, in exactly one category.

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
        if category not in CATEGORIES:
            raise ValueError(f"unknown error category {category!r}")
        super().__init__(redact_text(message, secrets))
        self.category = category
        self.status = status
        self.api_type = redact_text(api_type, secrets) if api_type else None
        self.api_code = api_code


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

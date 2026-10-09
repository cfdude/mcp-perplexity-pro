"""Logging to stderr with secrets removed from everything that is written.

Named ``log_setup`` so it does not shadow the standard library ``logging`` module.
stdout is reserved for MCP protocol messages in stdio mode, so nothing here ever writes to it.
"""

from __future__ import annotations

import logging
import re
import sys
import traceback
from collections.abc import Iterable
from typing import Any

REDACTED = "[redacted]"
HANDLER_NAME = "mcp_perplexity_pro"

# ``pplx-`` followed by key characters. Shorter than the 20-character shape the fixture scan
# uses, so a truncated key is caught as well.
_KEY_SHAPED = re.compile(r"pplx-[A-Za-z0-9_-]{8,}")

# Attributes every LogRecord has; anything else was passed through ``extra=``.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove each configured secret and any key-shaped token from ``text``."""
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return _KEY_SHAPED.sub(REDACTED, text)


class RedactingFilter(logging.Filter):
    """Redact the message, its arguments, exception text and string extras of every record."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = tuple(s for s in secrets if s)

    def _redact(self, text: str) -> str:
        return redact_text(text, self._secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a malformed format string must not leak its arguments
            message = f"{record.msg!s} {record.args!r}"
        record.msg = self._redact(message)
        record.args = None

        if record.exc_info:
            rendered = "".join(traceback.format_exception(*record.exc_info)).rstrip("\n")
            record.exc_text = self._redact(rendered)
            record.exc_info = None  # a handler must not re-render the unredacted traceback
        elif record.exc_text:
            record.exc_text = self._redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self._redact(record.stack_info)

        for name, value in list(record.__dict__.items()):
            if name not in _STANDARD_ATTRS and isinstance(value, str):
                setattr(record, name, self._redact(value))
        return True


def configure_logging(level: str = "INFO", secrets: Iterable[str] = ()) -> None:
    """Send all logging to stderr through a redacting handler. Safe to call repeatedly.

    FastMCP installs its own Rich handler on the ``fastmcp`` logger, which renders full
    tracebacks (source lines included) without redaction; that handler is detached so its
    records propagate to ours instead.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == HANDLER_NAME:
            root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter(secrets))
    root.addHandler(handler)
    root.setLevel(level.upper())

    fastmcp_logger = logging.getLogger("fastmcp")
    fastmcp_logger.handlers.clear()
    fastmcp_logger.propagate = True


def log_payload(logger: logging.Logger, label: str, payload: Any) -> None:
    """Log a request or response body. Emitted only at DEBUG, never at the default level."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("%s: %r", label, payload)

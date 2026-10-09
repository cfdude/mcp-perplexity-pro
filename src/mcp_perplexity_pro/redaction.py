"""Secret removal shared by logging and upstream error text."""

from __future__ import annotations

import re
from collections.abc import Iterable

REDACTED = "[redacted]"

# ``pplx-`` followed by key characters. Shorter than the 20-character shape the fixture scan
# uses, so a truncated key is caught as well.
_KEY_SHAPED = re.compile(r"pplx-[A-Za-z0-9_-]{8,}")


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove each configured secret and any key-shaped token from ``text``."""
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return _KEY_SHAPED.sub(REDACTED, text)

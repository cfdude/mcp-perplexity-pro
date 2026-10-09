"""Secret removal shared by logging and upstream error text."""

from __future__ import annotations

import re
from collections.abc import Iterable

REDACTED = "[redacted]"

# ``pplx-`` followed by key characters. Shorter than the 20-character shape the fixture scan
# uses, so a truncated key is caught as well. The documented Perplexity model ids
# (``pplx-embed-v1-0.6b``, ``pplx-embed-context-v1-4b``, ``pplx-decider-v1.1-27b``) are exempt:
# the lookahead skips ``embed-``/``decider-`` followed by at most 28 id characters that end the
# token, so a real key (alphanumeric, ~48 characters) and a partial echo of one still match.
_KEY_SHAPED = re.compile(
    r"pplx-(?!(?:embed|decider)-[A-Za-z0-9.-]{1,28}(?![A-Za-z0-9_-]))[A-Za-z0-9_-]{8,}"
)


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove each configured secret and any key-shaped token from ``text``."""
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return _KEY_SHAPED.sub(REDACTED, text)

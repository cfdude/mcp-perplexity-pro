"""Secret removal shared by logging and upstream error text."""

from __future__ import annotations

import re
from collections.abc import Iterable

REDACTED = "[redacted]"

# ``pplx-`` followed by key characters. Shorter than the 20-character shape the fixture scan
# uses, so a truncated key is caught as well. The documented Perplexity model ids
# (``pplx-embed-v1-0.6b``, ``pplx-embed-context-v1-4b``, ``pplx-decider-v1.1-27b``,
# ``pplx-decider-flash-v1.2``, ``perplexity/pplx-decider-latest``) are exempt, whatever precedes
# the ``pplx-`` (a ``perplexity/`` prefix included):
# the lookahead skips ``embed-``/``decider-`` followed by at most 28 id characters that end the
# token, so a real key (alphanumeric, ~48 characters) and a partial echo of one still match.
_KEY_SHAPED = re.compile(
    r"pplx-(?!(?:embed|decider)-[A-Za-z0-9.-]{1,28}(?![A-Za-z0-9_-]))[A-Za-z0-9_-]{8,}"
)


MEDIA_REMOVED = "[media removed]"

# A ``data:`` URI body runs from after ``data:`` to the first character outside this class
# (whitespace, quotes and brackets end it). Not preceded by a letter or digit, so ``metadata:x``
# is left alone. One character class under one ``+``: no backtracking.
_DATA_URI = re.compile(r"(?<![A-Za-z0-9])(data:)[A-Za-z0-9+/=;,.%_-]+", re.IGNORECASE)
# A bare run of the STANDARD base64 alphabet (not ``_`` or ``-``, so a ``pplx-``/``Qq7_`` key prefix
# stays for key redaction). A candidate is replaced only when it also looks like encoded bytes.
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/=]{200,}")
_UPPER = re.compile(r"[A-Z]")
_LOWER = re.compile(r"[a-z]")
_DIGIT = re.compile(r"[0-9]")


def _base64_run(match: re.Match[str]) -> str:
    run = match.group(0)
    if (
        _UPPER.search(run)
        and _LOWER.search(run)
        and _DIGIT.search(run)
        and run.count("/") * 16 <= len(run)
    ):
        return MEDIA_REMOVED
    return run


def scrub_media(text: str) -> str:
    """Replace ``data:`` URI bodies and bare base64 runs with ``[media removed]`` (one linear
    scan each), so an error that quotes a request never carries a file's bytes."""
    if "data:" in text.lower():
        text = _DATA_URI.sub(lambda m: m.group(1) + MEDIA_REMOVED, text)
    return _BASE64_RUN.sub(_base64_run, text)


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove media, each configured secret and any key-shaped token from ``text``.

    Media goes first, before key removal and before any caller truncates, so a base64 run that
    straddles a later cut is already gone."""
    text = scrub_media(text)
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return _KEY_SHAPED.sub(REDACTED, text)


def scrub_secrets(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove only the configured secrets from ``text``, never key-SHAPED tokens.

    For content the caller or the model supplied (a query, a title, an answer, a source URL): a
    ``pplx-`` shaped example in it is theirs to keep, but the configured key itself must never
    be stored or echoed back (server-runtime "Secrets are never emitted")."""
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return text

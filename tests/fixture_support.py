"""Shared helpers for recorded API fixtures: the key-shape scan used by the capture helper
and by ``test_fixtures.py``."""

import re
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# ``pplx-`` followed by 20 or more key characters, except a documented model id (``pplx-embed-...``
# or ``pplx-decider-...`` of at most 28 id characters that end the token, the rule of
# ``redaction.py``: ``pplx-decider-flash-latest`` is 20 characters long and is no key).
KEY_SHAPE = re.compile(
    r"pplx-(?!(?:embed|decider)-[A-Za-z0-9.-]{1,28}(?![A-Za-z0-9_-]))[A-Za-z0-9_\-]{20,}"
)

REQUIRED_META_KEYS = ("endpoint", "method", "http_status", "capture_date", "scrubbed")


def find_key_shapes(text: str) -> list[str]:
    """Return every key-shaped match in ``text`` (truncated, never the full match)."""
    return [m.group(0)[:8] + "..." for m in KEY_SHAPE.finditer(text)]

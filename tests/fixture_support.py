"""Shared helpers for recorded API fixtures: the key-shape scan used by the capture helper
and by ``test_fixtures.py``."""

import re
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# ``pplx-`` followed by 20 or more key characters.
KEY_SHAPE = re.compile(r"pplx-[A-Za-z0-9_\-]{20,}")

REQUIRED_META_KEYS = ("endpoint", "method", "http_status", "capture_date", "scrubbed")


def find_key_shapes(text: str) -> list[str]:
    """Return every key-shaped match in ``text`` (truncated, never the full match)."""
    return [m.group(0)[:8] + "..." for m in KEY_SHAPE.finditer(text)]

"""The live-capture scrub removes addresses and keeps versioned presets (api-drift-2026-10)."""

import pytest
from test_live_capture import EMAIL, scrub


@pytest.mark.parametrize(
    "text", ["x@sub.2fa.io", "ops@mail.1password.com", "a.b+c@example.com", "mail me@x.co now"]
)
def test_an_address_is_scrubbed(text):
    assert EMAIL.search(text)


@pytest.mark.parametrize("text", ["fast@2026-10-16.0", "low@2026-10-24.0", "fast@2026-10-16.0 ok"])
def test_a_versioned_preset_is_kept(text):
    removed: list[str] = []
    assert scrub(text, "p", removed) == text
    assert removed == []

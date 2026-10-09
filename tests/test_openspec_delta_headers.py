"""Task 4.2: a change's MODIFIED requirement headers must name requirements that exist in the main
spec, and its ADDED ones must not (OpenSpec matches headers by exact name, and a misspelled
MODIFIED header silently becomes a second requirement at sync time).

It skips once the change has moved to ``openspec/changes/archive/``: after the sync the headers
are the main spec's own.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHANGE = ROOT / "openspec" / "changes" / "py-usage-log"
MAIN = ROOT / "openspec" / "specs"
SECTION = re.compile(r"^## (ADDED|MODIFIED|REMOVED|RENAMED) Requirements\s*$", re.M)
HEADER = re.compile(r"^### Requirement: (.+?)\s*$", re.M)

pytestmark = pytest.mark.skipif(
    not CHANGE.is_dir(),
    reason="py-usage-log has moved to openspec/changes/archive/: its delta headers are now the "
    "main spec's own",
)


def delta_headers(text: str) -> dict[str, list[str]]:
    """Requirement names under each ``## ADDED|MODIFIED|... Requirements`` heading of a delta."""
    marks = list(SECTION.finditer(text))
    found: dict[str, list[str]] = {}
    for mark, following in zip(marks, [*marks[1:], None], strict=True):
        body = text[mark.end() : following.start() if following else len(text)]
        found.setdefault(mark.group(1), []).extend(HEADER.findall(body))
    return found


def main_headers(text: str) -> set[str]:
    return set(HEADER.findall(text))


def problems(delta_text: str, main_text: str | None) -> list[str]:
    """Why the delta's headers do not line up with the main spec (empty when they do)."""
    found = delta_headers(delta_text)
    existing = main_headers(main_text) if main_text is not None else set()
    out = [
        f"MODIFIED {name!r} is not a requirement of the main spec"
        for name in found.get("MODIFIED", [])
        if name not in existing
    ]
    out += [
        f"ADDED {name!r} already exists in the main spec"
        for name in found.get("ADDED", [])
        if name in existing
    ]
    return out


DELTAS = sorted(CHANGE.glob("specs/*/spec.md")) if CHANGE.is_dir() else []


@pytest.mark.parametrize("delta", DELTAS, ids=lambda p: p.parent.name)
def test_delta_headers_line_up_with_the_main_spec(delta):
    main = MAIN / delta.parent.name / "spec.md"
    main_text = main.read_text() if main.is_file() else None
    assert problems(delta.read_text(), main_text) == []


# --- the checker itself must fail on a bad header (so a green run means something) -------------

MAIN_TEXT = "## Requirements\n\n### Requirement: Project resolution\n\n### Requirement: Other\n"


def test_a_misspelled_modified_header_is_reported():
    delta = "## MODIFIED Requirements\n\n### Requirement: Project resolutions\n"
    assert problems(delta, MAIN_TEXT) == [
        "MODIFIED 'Project resolutions' is not a requirement of the main spec"
    ]


def test_an_added_header_that_already_exists_is_reported():
    delta = "## ADDED Requirements\n\n### Requirement: Other\n"
    assert problems(delta, MAIN_TEXT) == ["ADDED 'Other' already exists in the main spec"]


def test_a_modified_header_with_no_main_spec_is_reported():
    delta = "## MODIFIED Requirements\n\n### Requirement: Anything\n"
    assert problems(delta, None) == ["MODIFIED 'Anything' is not a requirement of the main spec"]


def test_correct_headers_pass_and_sections_are_kept_apart():
    delta = (
        "## ADDED Requirements\n\n### Requirement: New one\n\n"
        "## MODIFIED Requirements\n\n### Requirement: Project resolution\n"
    )
    assert delta_headers(delta) == {"ADDED": ["New one"], "MODIFIED": ["Project resolution"]}
    assert problems(delta, MAIN_TEXT) == []

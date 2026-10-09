"""Task 4.2 (py-usage-log) and 1.4 (py-agent-api): the MODIFIED requirement headers of EVERY
active change must name requirements that exist in the main spec, and its ADDED ones must not
(OpenSpec matches headers by exact name, and a misspelled MODIFIED header silently becomes a
second requirement at sync time).

Active means a directory under ``openspec/changes/`` other than ``archive/``. With none (every
change archived: the headers are then the main spec's own) the check skips.
"""

import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHANGES = ROOT / "openspec" / "changes"
MAIN = ROOT / "openspec" / "specs"
SECTION = re.compile(r"^## (ADDED|MODIFIED|REMOVED|RENAMED) Requirements\s*$", re.M)
HEADER = re.compile(r"^### Requirement: (.+?)\s*$", re.M)


def active_deltas(changes_dir: Path) -> list[Path]:
    """Every delta spec of every active (non-``archive``) change."""
    if not changes_dir.is_dir():
        return []
    return sorted(
        delta
        for delta in changes_dir.glob("*/specs/*/spec.md")
        if delta.relative_to(changes_dir).parts[0] != "archive"
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


def check_changes(changes_dir: Path, main_dir: Path) -> list[str]:
    """Header problems of every active change under ``changes_dir`` against ``main_dir``."""
    out = []
    for delta in active_deltas(changes_dir):
        main = main_dir / delta.parent.name / "spec.md"
        main_text = main.read_text() if main.is_file() else None
        label = f"{delta.relative_to(changes_dir).parts[0]}/{delta.parent.name}"
        out += [f"{label}: {p}" for p in problems(delta.read_text(), main_text)]
    return out


DELTAS = active_deltas(CHANGES)


@pytest.mark.skipif(not DELTAS, reason="no active change: every delta is archived into main")
@pytest.mark.parametrize(
    "delta", DELTAS or [None], ids=lambda p: f"{p.parent.parent.parent.name}/{p.parent.name}"
)
def test_delta_headers_line_up_with_the_main_spec(delta):
    main = MAIN / delta.parent.name / "spec.md"
    main_text = main.read_text() if main.is_file() else None
    assert problems(delta.read_text(), main_text) == []


def test_every_active_change_is_checked_not_a_hard_coded_one():
    names = {d.parent.parent.parent.name for d in DELTAS}
    assert "archive" not in names
    assert names == {d.name for d in CHANGES.iterdir() if list(d.glob("specs/*/spec.md"))} - {
        "archive"
    }


def test_a_misspelled_modified_header_in_a_scratch_copy_goes_red(tmp_path):
    scratch = tmp_path / "changes"
    shutil.copytree(CHANGES, scratch, ignore=shutil.ignore_patterns("archive"))
    assert check_changes(scratch, MAIN) == []  # the real active changes are clean
    victims = [
        p
        for p in active_deltas(scratch)
        if "### Requirement: Configuration from environment" in p.read_text()
    ]
    assert victims, "no active change modifies 'Configuration from environment'"
    for victim in victims:
        victim.write_text(
            victim.read_text().replace(
                "### Requirement: Configuration from environment",
                "### Requirement: Configuration from environments",
            )
        )
    result = check_changes(scratch, MAIN)
    assert result and all("Configuration from environments" in line for line in result)


def test_an_archived_change_is_not_checked(tmp_path):
    changes = tmp_path / "changes"
    bad = changes / "archive" / "old" / "specs" / "x"
    bad.mkdir(parents=True)
    (bad / "spec.md").write_text("## MODIFIED Requirements\n\n### Requirement: Nope\n")
    assert active_deltas(changes) == []
    assert check_changes(changes, tmp_path) == []


def test_no_changes_directory_means_nothing_to_check(tmp_path):
    assert active_deltas(tmp_path / "missing") == []


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

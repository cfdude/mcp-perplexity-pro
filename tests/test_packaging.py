"""Assert pyproject.toml packages the migrations directory (offline; no build is run)."""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "src/mcp_perplexity_pro"
MIGRATION_FILES = ("env.py", "script.py.mako", "versions/0001_initial.py")


@pytest.fixture(scope="module")
def wheel_config() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"][
        "targets"
    ]["wheel"]


def test_build_backend_is_hatchling():
    build = tomllib.loads((ROOT / "pyproject.toml").read_text())["build-system"]
    assert build["build-backend"] == "hatchling.build"


def test_wheel_packages_the_whole_package_tree(wheel_config):
    assert PACKAGE in wheel_config["packages"]


def test_wheel_has_no_filter_that_could_drop_migration_files(wheel_config):
    # hatchling packages every non-ignored file under a listed package; any of these
    # keys would narrow that and could silently drop the .mako template.
    assert not {"include", "only-include", "exclude", "only-packages"} & set(wheel_config)


@pytest.mark.parametrize("name", MIGRATION_FILES)
def test_migration_file_lives_under_the_packaged_tree(name):
    path = ROOT / PACKAGE / "migrations" / name
    assert path.is_file()
    assert path.is_relative_to(ROOT / PACKAGE)


def test_migration_files_are_not_gitignored():
    # hatchling honours .gitignore, so an ignore rule would drop them from the wheel.
    patterns = [
        line.strip()
        for line in (ROOT / ".gitignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    for banned in ("migrations", "migrations/", "*.mako", "versions", "versions/"):
        assert banned not in patterns

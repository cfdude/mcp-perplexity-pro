"""Assert the quality-gate settings in pyproject.toml so they cannot drift silently."""

import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@pytest.fixture(scope="module")
def config() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def test_ruff_line_length_is_100(config):
    assert config["tool"]["ruff"]["line-length"] == 100


def test_ruff_is_the_only_linter_and_formatter(config):
    tools = set(config["tool"])
    assert not tools & {"black", "isort", "flake8", "pylint", "autopep8", "yapf", "mypy"}


def test_ruff_covers_python_only(config):
    excluded = config["tool"]["ruff"]["extend-exclude"]
    assert "node_modules" in excluded
    assert "dist" in excluded


def test_pytest_settings(config):
    opts = config["tool"]["pytest"]["ini_options"]
    assert opts["testpaths"] == ["tests"]
    assert opts["asyncio_mode"] == "auto"
    assert opts["addopts"] == "-m 'not live and not build'"
    assert any(m.startswith("live:") for m in opts["markers"])
    assert any(m.startswith("allow_network:") for m in opts["markers"])
    assert any(m.startswith("build:") for m in opts["markers"])


def test_fastmcp_deprecations_are_errors(config):
    filters = config["tool"]["pytest"]["ini_options"]["filterwarnings"]
    assert "error::fastmcp.exceptions.FastMCPDeprecationWarning" in filters


def test_project_metadata(config):
    project = config["project"]
    assert project["name"] == "mcp-perplexity-pro"
    assert project["version"] == "2.0.0"
    assert project["requires-python"] == ">=3.12"

"""pypi-publish task 1.1: the package metadata and the README's links (package-release spec)."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
PROJECT = PYPROJECT["project"]


def test_the_license_is_an_spdx_expression_with_its_file():
    assert PROJECT["license"] == "MIT"
    assert PROJECT["license-files"] == ["LICENSE"]
    text = (ROOT / "LICENSE").read_text()
    assert text.startswith("MIT License") and "Rob Sherman" in text


def test_the_build_backend_emits_pep_639_metadata():
    requires = PYPROJECT["build-system"]["requires"]
    assert any(r.replace(" ", "").startswith("hatchling>=1.27") for r in requires), requires


def test_there_is_no_license_classifier_next_to_the_spdx_field():
    assert not [c for c in PROJECT["classifiers"] if c.startswith("License ::")]


def test_classifiers_name_only_the_versions_ci_runs():
    versions = {
        c for c in PROJECT["classifiers"] if c.startswith("Programming Language :: Python :: 3.")
    }
    assert versions == {
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.14",
    }
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert '"3.12", "3.14"' in ci  # the classifiers say what CI tests
    assert any(c.startswith("Development Status ::") for c in PROJECT["classifiers"])


def test_authors_keywords_urls_and_readme():
    assert PROJECT["authors"] == [{"name": "Rob Sherman"}]
    assert {"mcp", "perplexity", "cli"} <= set(PROJECT["keywords"])
    urls = PROJECT["urls"]
    assert set(urls) >= {"Repository", "Changelog", "Issues"}
    assert all(u.startswith("https://github.com/cfdude/mcp-perplexity-pro") for u in urls.values())
    assert PROJECT["readme"] == "README.md"
    assert (ROOT / "README.md").exists() and (ROOT / "CHANGELOG.md").exists()


def test_both_entry_points_are_declared():
    assert PROJECT["scripts"] == {
        "mcp-perplexity-pro": "mcp_perplexity_pro.__main__:main",
        "perplexity-pro": "mcp_perplexity_pro.command:cli",
    }


def test_the_sdist_include_is_anchored():
    include = PYPROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert include == [
        "/src",
        "/tests",
        "/README.md",
        "/CHANGELOG.md",
        "/LICENSE",
        "/pyproject.toml",
        "/uv.lock",
    ]
    assert all(entry.startswith("/") for entry in include)  # a bare name matches at any depth


def test_every_markdown_link_in_the_readme_is_absolute_or_an_anchor():
    text = (ROOT / "README.md").read_text()
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)  # code blocks are not links
    text = re.sub(r"`[^`\n]*`", "", text)  # nor is inline code
    targets = re.findall(r"\]\(([^)\s]+)", text)
    bad = [t for t in targets if not t.startswith(("http://", "https://", "mailto:", "#"))]
    assert not bad, bad


def test_the_readme_documents_every_install_path_from_pypi():
    text = (ROOT / "README.md").read_text()
    for needle in (
        "uvx mcp-perplexity-pro",
        "uvx --from mcp-perplexity-pro perplexity-pro",
        "uv tool install mcp-perplexity-pro",
        "pipx install mcp-perplexity-pro",
        '"command": "uvx"',
    ):
        assert needle in text, needle
    # the command-line name is only ever shown through --from (the name is not registered)
    assert not re.search(r"uvx perplexity-pro", text)


def test_the_release_guide_names_the_workflow_and_environments_the_workflow_uses():
    import yaml

    guide = (ROOT / "docs/releasing.md").read_text()
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    assert "release.yml" in guide and (ROOT / ".github/workflows/release.yml").exists()
    environments = {job["environment"] for job in workflow["jobs"].values() if "environment" in job}
    assert environments == {"pypi", "testpypi"}
    for name in environments:
        assert f"environment `{name}`" in guide or f"`{name}`" in guide, name
    for heading in (
        "One-time setup",
        "Checklist before a tag",
        "Rehearse on TestPyPI",
        "If a release is bad",
    ):
        assert heading in guide, heading
    assert "Yank" in guide or "yank" in guide

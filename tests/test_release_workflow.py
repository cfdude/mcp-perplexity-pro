"""pypi-publish task 2.1: the release workflow's shape and safety rules (package-release spec)."""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / ".github/workflows/release.yml").read_text()
DATA = yaml.safe_load(TEXT)
JOBS = DATA["jobs"]
TRIGGERS = DATA.get(True)  # PyYAML reads the key `on:` as the boolean True


def steps(job):
    return JOBS[job]["steps"]


def step_named(job, fragment):
    (found,) = [s for s in steps(job) if fragment in s.get("name", "")]
    return found


def test_triggers_are_a_version_tag_and_a_manual_run():
    assert TRIGGERS["push"]["tags"] == ["v*"]
    assert "workflow_dispatch" in TRIGGERS


def test_no_token_password_or_secret_exists():
    assert "secrets." not in TEXT
    assert not re.search(r"^\s*password:", TEXT, flags=re.MULTILINE)


def test_id_token_write_only_on_the_two_publish_jobs_each_in_an_environment():
    assert DATA["permissions"] == {"contents": "read"}
    for name, job in JOBS.items():
        granted = (job.get("permissions") or {}).get("id-token") == "write"
        assert granted == name.startswith("publish-"), name
    assert JOBS["publish-pypi"]["environment"] == "pypi"
    assert JOBS["publish-testpypi"]["environment"] == "testpypi"
    for name in ("publish-pypi", "publish-testpypi"):
        assert JOBS[name]["needs"] == "build"


def test_a_tag_publishes_to_pypi_and_a_dispatch_only_to_testpypi():
    assert JOBS["publish-pypi"]["if"] == "github.event_name == 'push'"
    assert JOBS["publish-testpypi"]["if"] == "github.event_name == 'workflow_dispatch'"
    pypi = steps("publish-pypi")[-1]
    testpypi = steps("publish-testpypi")[-1]
    assert "with" not in pypi  # the default repository is PyPI
    assert testpypi["with"]["repository-url"] == "https://test.pypi.org/legacy/"


def test_the_build_job_checks_before_anything_is_published():
    names = [s.get("name", s.get("uses", "")) for s in steps("build")]
    joined = " | ".join(names)
    for fragment in (
        "Lint",
        "Format check",
        "Test",
        "Build tests",
        "tag must equal",
        "development version",
        "Check the package metadata",
        "clean environment",
    ):
        assert fragment in joined, fragment
    runs = {s.get("name", ""): s.get("run", "") for s in steps("build")}
    assert "uv run pytest -m build" in runs["Build tests"]
    assert "twine@7.0.0 check" in runs["Check the package metadata"]
    clean = runs["Install the wheel in a clean environment and run both commands"]
    assert "mcp-perplexity-pro --version" in clean and "perplexity-pro help ask" in clean
    assert "--locked" in runs["Install dependencies from the lockfile"]
    assert step_named("build", "tag must equal")["if"] == "github.event_name == 'push'"
    assert (
        step_named("build", "development version")["if"]
        == "github.event_name == 'workflow_dispatch'"
    )


def test_actions_are_pinned_to_a_major_except_the_publish_action():
    uses = [s["uses"] for job in JOBS.values() for s in job["steps"] if "uses" in s]
    for ref in uses:
        name, _, version = ref.partition("@")
        if name == "pypa/gh-action-pypi-publish":
            assert version == "release/v1"  # it has no major tag
        else:
            assert re.fullmatch(r"v\d+", version), ref


def run_script(fragment, cwd, **env):
    script = step_named("build", fragment)["run"]
    return subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"], **env},
    )


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "2.0.0"\n')
    return tmp_path


def test_the_tag_check_accepts_the_version_and_refuses_another(project):
    assert run_script("tag must equal", project, GITHUB_REF_NAME="v2.0.0").returncode == 0
    bad = run_script("tag must equal", project, GITHUB_REF_NAME="v2.0.1")
    assert bad.returncode == 1 and "v2.0.1" in bad.stderr


def test_a_rehearsal_rewrites_the_version_to_a_dev_version(project):
    result = run_script("development version", project, GITHUB_RUN_NUMBER="7")
    assert result.returncode == 0, result.stderr
    assert 'version = "2.0.0.dev7"' in (project / "pyproject.toml").read_text()

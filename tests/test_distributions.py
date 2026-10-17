"""pypi-publish task 1.1: what the built source distribution and wheel contain (build marker)."""

import re
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = ("src/", "tests/", "README.md", "CHANGELOG.md", "LICENSE", "pyproject.toml", "uv.lock")
ALWAYS = {".gitignore", "PKG-INFO"}  # hatchling adds both to every sdist
FORBIDDEN = re.compile(
    r"(^|/)(openspec|\.conductor|docs|\.github|node_modules|dist)/|(^|/)"
    r"(CLAUDE\.md|PROJECT\.md|ecosystem\.config\.cjs|\.env[^/]*)$"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    proc = subprocess.run(
        ["uv", "build", "--out-dir", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    (sdist,) = out.glob("*.tar.gz")
    (wheel,) = out.glob("*.whl")
    return sdist, wheel


def sdist_paths(sdist):
    with tarfile.open(sdist) as tar:
        names = [m.name for m in tar.getmembers() if m.isfile()]
    return [n.split("/", 1)[1] for n in names]


@pytest.mark.build
def test_the_sdist_holds_only_the_allowlist(built):
    sdist, _ = built
    paths = sdist_paths(sdist)
    stray = [p for p in paths if p not in ALWAYS and not p.startswith(ALLOWED)]
    assert not stray, stray[:10]
    assert not [p for p in paths if FORBIDDEN.search(p)]
    # an unanchored include would pull in a README.md from any subdirectory
    assert not [p for p in paths if p.endswith("README.md") and p != "README.md"]
    assert "LICENSE" in paths and "README.md" in paths and "CHANGELOG.md" in paths


@pytest.mark.build
def test_the_wheel_has_the_license_metadata_entry_points_and_migrations(built):
    _, wheel = built
    zf = zipfile.ZipFile(wheel)
    names = zf.namelist()
    (meta,) = [n for n in names if n.endswith(".dist-info/METADATA")]
    text = zf.read(meta).decode()
    assert "License-Expression: MIT" in text and "Author: Rob Sherman" in text
    assert "Project-URL: Repository, https://github.com/cfdude/mcp-perplexity-pro" in text
    assert "Project-URL: Changelog," in text and "Project-URL: Issues," in text
    assert "Classifier: Programming Language :: Python :: 3.12" in text
    assert "Classifier: Programming Language :: Python :: 3.14" in text
    assert "Classifier: License ::" not in text
    (keywords,) = re.findall(r"^Keywords: (.*)$", text, flags=re.MULTILINE)
    assert {"mcp", "perplexity", "cli"} <= set(keywords.split(","))
    assert any(n.endswith(".dist-info/licenses/LICENSE") for n in names)
    (entry,) = [n for n in names if n.endswith("entry_points.txt")]
    scripts = zf.read(entry).decode()
    assert "mcp-perplexity-pro = mcp_perplexity_pro.__main__:main" in scripts
    assert "perplexity-pro = mcp_perplexity_pro.command:cli" in scripts
    assert "mcp_perplexity_pro/migrations/versions/0005_embedding_chunks.py" in names
    # model-matrix: the baseline matrix is data inside the package, read with importlib.resources
    assert "mcp_perplexity_pro/data/model_matrix_baseline.json" in names


@pytest.mark.build
def test_the_wheel_builds_from_the_trimmed_sdist(built):
    sdist, wheel = built
    assert wheel.exists() and sdist.exists()  # `uv build` builds the wheel from the sdist

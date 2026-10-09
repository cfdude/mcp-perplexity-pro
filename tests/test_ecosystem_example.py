"""The committed pm2 example stays valid, key-free and consistent with the server-runtime spec.

``ecosystem.config.cjs`` (the real one, holding the key) is gitignored; this example is what a
fresh checkout copies. Offline: the file is read as text, and loaded with ``node`` only when
``node`` is installed.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parent.parent / "ecosystem.example.cjs"
GRACEFUL_SHUTDOWN_SECONDS = 10  # __main__.GRACEFUL_TIMEOUT: in-flight calls may take this long
KEY_SHAPE = re.compile(r"pplx-[A-Za-z0-9_\-]{8,}")


@pytest.fixture(scope="module")
def text() -> str:
    return EXAMPLE.read_text()


def test_kill_timeout_is_at_least_15_seconds(text):
    """server-runtime spec, scenario "Configured kill timeout"."""
    match = re.search(r"kill_timeout\s*:\s*(\d+)", text)
    assert match, "ecosystem.example.cjs sets no kill_timeout"
    assert int(match.group(1)) >= 15000


def test_kill_timeout_exceeds_the_server_shutdown_bound(text):
    from mcp_perplexity_pro.__main__ import GRACEFUL_TIMEOUT

    assert GRACEFUL_TIMEOUT == GRACEFUL_SHUTDOWN_SECONDS
    kill_ms = int(re.search(r"kill_timeout\s*:\s*(\d+)", text).group(1))
    assert kill_ms > GRACEFUL_TIMEOUT * 1000


def test_runs_the_http_entry_point(text):
    assert "mcp-perplexity-pro" in text
    assert re.search(r"args\s*:\s*'[^']*--transport http'", text)


def test_contains_no_key(text):
    assert not KEY_SHAPE.search(text)
    assert re.search(r"PERPLEXITY_API_KEY\s*:\s*'REPLACE_ME'", text)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_loads_in_node():
    script = "console.log(JSON.stringify(require(process.argv[1])))"
    out = subprocess.run(
        ["node", "-e", script, str(EXAMPLE)], capture_output=True, text=True, check=True
    ).stdout
    app = json.loads(out)["apps"][0]
    assert app["name"] == "mcp-perplexity-pro"
    assert app["kill_timeout"] >= 15000
    assert app["env"]["PERPLEXITY_API_KEY"] == "REPLACE_ME"
    assert app["env"]["PERPLEXITY_PORT"] == "8102"

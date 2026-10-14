"""py-cli task 4.1: ``perplexity-pro serve`` and the two entry points (cli spec)."""

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import httpx2
import pytest
from server_support import free_port, server_env

ROOT = Path(__file__).resolve().parent.parent


def health(tmp_path, module_args):
    """Start a server subprocess on an ephemeral port, wait for /health, stop it."""
    import time

    port = free_port()
    env = server_env(tmp_path, PERPLEXITY_PORT=str(port))
    proc = subprocess.Popen(
        [sys.executable, "-m", *module_args, "--transport", "http"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=tmp_path,
    )
    try:
        for _ in range(100):
            try:
                reply = httpx2.get(f"http://127.0.0.1:{port}/health", timeout=1)
                return reply.status_code, reply.json()
            except httpx2.TransportError:
                time.sleep(0.1)
        raise AssertionError("the server never answered /health")
    finally:
        proc.terminate()
        proc.wait(timeout=20)


def test_serve_over_http_answers_health(tmp_path):
    status, body = health(tmp_path, ["mcp_perplexity_pro.command", "serve"])
    assert status == 200 and body["status"] == "ok"


def test_the_old_command_still_serves(tmp_path):
    status, body = health(tmp_path, ["mcp_perplexity_pro"])
    assert status == 200 and body["status"] == "ok"


def test_both_entry_points_are_declared():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["mcp-perplexity-pro"] == "mcp_perplexity_pro.__main__:main"
    assert scripts["perplexity-pro"] == "mcp_perplexity_pro.command:cli"


def test_serve_help_lists_the_transports(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "mcp_perplexity_pro.command", "serve", "--help"],
        env=server_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0 and "stdio,http" in result.stdout.replace(" ", "")


@pytest.mark.build
def test_the_built_wheel_declares_both_commands(tmp_path):
    out = tmp_path / "wheel"
    proc = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    (wheel,) = out.glob("*.whl")
    names = zipfile.ZipFile(wheel).namelist()
    assert "mcp_perplexity_pro/command.py" in names
    (entry,) = [n for n in names if n.endswith("entry_points.txt")]
    text = zipfile.ZipFile(wheel).read(entry).decode()
    assert "perplexity-pro = mcp_perplexity_pro.command:cli" in text
    assert "mcp-perplexity-pro = mcp_perplexity_pro.__main__:main" in text

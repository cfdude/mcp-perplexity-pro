"""Argument parsing happens before settings load, so --help needs no environment."""

import subprocess
import sys

import pytest

from mcp_perplexity_pro import cli


def run_cli(*args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "mcp_perplexity_pro.cli", *args],
        env={} if env is None else env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_help_works_with_an_empty_environment():
    result = run_cli("--help")
    assert result.returncode == 0, result.stderr
    assert "--transport" in result.stdout
    assert "PERPLEXITY_API_KEY" in result.stdout
    assert "PERPLEXITY_AGENT_READ_TIMEOUT" in result.stdout
    assert result.stderr == ""


def test_version_works_with_an_empty_environment():
    result = run_cli("--version")
    assert result.returncode == 0, result.stderr
    assert "2.0.0" in result.stdout


def test_bad_transport_is_a_usage_error_not_a_settings_error():
    result = run_cli("--transport", "carrier-pigeon")
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert "PERPLEXITY_API_KEY" not in result.stderr


@pytest.mark.parametrize(("argv", "expected"), [([], "stdio"), (["--transport", "http"], "http")])
def test_transport_parsing(argv, expected):
    assert cli.parse_args(argv).transport == expected


def test_importing_cli_does_not_load_settings():
    code = (
        "import sys, mcp_perplexity_pro.cli\nsys.exit('mcp_perplexity_pro.settings' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], env={}, capture_output=True, timeout=60)
    assert result.returncode == 0

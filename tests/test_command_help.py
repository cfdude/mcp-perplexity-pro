"""py-cli task 3.1: --help, the help subcommand and the command-line help style (cli spec)."""

import asyncio
import os
import shlex
import subprocess
import sys
from importlib.metadata import version

import pytest
from agent_support import make_world, respond_with

from mcp_perplexity_pro import command, help_text
from mcp_perplexity_pro.command import cli_example, main, parse_command, schema_source

TIERS = {
    "PERPLEXITY_ROUTING": "custom",
    "PERPLEXITY_TIER_LIGHT": "x/light",
    "PERPLEXITY_TIER_STANDARD": "x/standard",
    "PERPLEXITY_TIER_COMPLEX": "x/complex",
}


@pytest.fixture(scope="module")
def tools():
    return schema_source()


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("PERPLEXITY_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PERPLEXITY_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def run_cli(tmp_path, *argv, **env_extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PERPLEXITY_")}
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env.update(HOME=str(home), PERPLEXITY_DATA_DIR=str(tmp_path / "data"), **env_extra)
    return subprocess.run(
        [sys.executable, "-m", "mcp_perplexity_pro.command", *argv],
        env=env,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=60,
    )


def test_help_needs_no_key_no_network_no_data_directory(tmp_path):
    result = run_cli(tmp_path, "help")
    assert result.returncode == 0, result.stderr
    assert (
        result.stdout.startswith("# perplexity-pro ")
        and "perplexity-pro help <tool>" in result.stdout
    )
    assert not (tmp_path / "data").exists() and result.stderr == ""


def test_help_survives_an_invalid_environment_with_one_warning(tmp_path):
    result = run_cli(tmp_path, "help", PERPLEXITY_PORT="nope")
    assert result.returncode == 0 and "Routing: standard" in result.stdout
    assert result.stderr.count("environment is invalid") == 1


def test_a_tool_page_has_a_command_line_example_and_accepts_the_prefix(clean_env, capsys):
    assert main(["help", "ask"]) == 0
    page = capsys.readouterr().out
    assert page.startswith("# perplexity_ask") and "perplexity-pro ask" in page
    assert '{"name"' not in page
    assert main(["help", "perplexity_ask"]) == 0
    assert capsys.readouterr().out == page


async def mcp_text(make_settings, action, name, **settings):
    w = await make_world(make_settings, respond_with("agent_fast.json"), **settings)
    try:
        return (await w.call("perplexity_help", action=action, name=name)).structured_content[
            "text"
        ]
    finally:
        await w.aclose()


@pytest.mark.parametrize("topic", help_text.TOPICS)
async def test_topic_pages_are_identical_to_the_mcp_tool(make_settings, clean_env, capsys, topic):
    expected = await mcp_text(make_settings, "topic", topic)
    words = ["help", "topic", topic] if topic == "projects" else ["help", topic]
    assert await asyncio.to_thread(main, words) == 0
    assert capsys.readouterr().out == expected


async def test_the_routing_topic_matches_on_a_custom_server(
    make_settings, clean_env, monkeypatch, capsys
):
    expected = await mcp_text(
        make_settings,
        "topic",
        "routing",
        routing="custom",
        tier_light="x/light",
        tier_standard="x/standard",
        tier_complex="x/complex",
    )
    for name, value in TIERS.items():
        monkeypatch.setenv(name, value)
    assert await asyncio.to_thread(main, ["help", "routing"]) == 0
    assert capsys.readouterr().out == expected


async def test_tool_pages_and_the_index_differ_only_in_example_and_pointer(
    make_settings, clean_env, capsys
):
    for action, name, cli_args in (
        ("tool", "perplexity_search", ["help", "search"]),
        ("index", None, ["help"]),
    ):
        mcp = (await mcp_text(make_settings, action, name)).splitlines()
        assert await asyncio.to_thread(main, cli_args) == 0
        cli = capsys.readouterr().out.splitlines()
        assert len(mcp) == len(cli)
        different = [i for i, (a, b) in enumerate(zip(mcp, cli, strict=True)) if a != b]
        for i in different:
            assert "perplexity_help" in mcp[i] or mcp[i].startswith('{"name"') or "More:" in mcp[i]
        assert 0 < len(different) <= 3


def test_every_example_round_trips_through_the_parser(tools):
    for tool in tools:
        entry = help_text.TOOLS.get(tool.name)
        if tool.name == "perplexity_help" or entry is None:
            continue
        line = cli_example(tool, entry["example"])
        ns, arguments = parse_command(shlex.split(line)[1:], tools)
        assert arguments == entry["example"], (tool.name, line, arguments)


def test_a_command_help_shows_summary_cost_and_a_command_line_example(tools, capsys):
    with pytest.raises(SystemExit) as info:
        parse_command(["ask", "--help"], tools)
    assert info.value.code == 0
    out = capsys.readouterr().out
    assert (
        "usage: perplexity-pro ask" in out and help_text.TOOLS["perplexity_ask"]["summary"] in out
    )
    assert "cost:" in out and "example:" in out and "perplexity-pro ask 'What is the latest" in out
    assert "--depth" in out and "--tier" in out


def test_unknown_names_list_the_valid_ones(clean_env, capsys):
    assert main(["help", "pricing"]) == 1
    err = capsys.readouterr().err
    assert "ask" in err and "costs" in err and "no help for 'pricing'" in err


def test_version_needs_nothing(tmp_path):
    result = run_cli(tmp_path, "--version")
    assert result.returncode == 0 and version("mcp-perplexity-pro") in result.stdout


_ = command

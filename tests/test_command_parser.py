"""py-cli task 1.1: the offline parser generated from the tool schemas (cli spec)."""

import json
import os
import socket
import subprocess
import sys

import pytest

from mcp_perplexity_pro import command
from mcp_perplexity_pro.command import ToolSpec, build_parser, parse_command, schema_source


@pytest.fixture(scope="module")
def tools():
    return schema_source()


def parse(tools, *argv):
    ns, arguments = parse_command(list(argv), tools)
    return ns, arguments


def refused(tools, capsys, *argv):
    with pytest.raises(SystemExit) as info:
        parse(tools, *argv)
    assert info.value.code == 2
    return capsys.readouterr().err


def test_the_schema_source_lists_every_tool_with_its_command_name(tools):
    names = {t.name for t in tools}
    assert "perplexity_ask" in names and "perplexity_help" in names and len(names) == 11
    assert {t.command for t in tools} >= {"ask", "chat", "research", "jobs", "search", "usage"}


def test_the_top_level_help_lists_every_command(tools, capsys):
    with pytest.raises(SystemExit) as info:
        parse(tools, "--help")
    assert info.value.code == 0
    out = capsys.readouterr().out
    for name in (
        "ask",
        "chat",
        "research",
        "jobs",
        "search",
        "decide",
        "embed",
        "models",
        "projects",
        "usage",
        "help",
        "serve",
    ):
        assert name in out


def test_positionals_and_flags(tools):
    ns, args = parse(
        tools,
        "ask",
        "what is new?",
        "--depth",
        "fast",
        "--domains",
        "python.org",
        "--domains",
        "docs.python.org",
    )
    assert args == {
        "query": "what is new?",
        "depth": "fast",
        "domains": ["python.org", "docs.python.org"],
    }


def test_chat_takes_action_positionally_and_the_rest_as_flags(tools):
    ns, args = parse(tools, "chat", "send", "--title", "t", "--message", "hello", "--chat-id", "3")
    assert args == {"action": "send", "title": "t", "message": "hello", "chat_id": 3}


def test_booleans_are_tri_state_and_untouched_parameters_are_absent(tools):
    assert parse(tools, "ask", "q", "--no-search")[1] == {"query": "q", "search": False}
    assert parse(tools, "ask", "q", "--search")[1] == {"query": "q", "search": True}
    assert parse(tools, "ask", "q")[1] == {"query": "q"}  # no nulls, no defaults


def test_search_takes_one_or_several_queries(tools):
    assert parse(tools, "search", "rust")[1] == {"query": "rust"}
    assert parse(tools, "search", "rust", "zig")[1] == {"query": ["rust", "zig"]}


def test_a_value_that_starts_with_a_dash(tools):
    assert parse(tools, "search", "q", "--domains=-reddit.com")[1]["domains"] == ["-reddit.com"]
    assert parse(tools, "ask", "--", "-weird query")[1] == {"query": "-weird query"}


def test_json_from_a_string_a_file_and_stdin(tools, tmp_path, monkeypatch):
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema))
    assert parse(tools, "ask", "q", "--json-schema", f"@{path}")[1]["json_schema"] == schema
    assert parse(tools, "ask", "q", "--json-schema", json.dumps(schema))[1]["json_schema"] == schema
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(schema)))
    assert parse(tools, "ask", "q", "--json-schema", "-")[1]["json_schema"] == schema


def test_untyped_state_is_text_or_json(tools):
    q = json.dumps({"u": {"type": "noul", "criteria": {"true": "a", "false": "b"}}})
    text = parse(tools, "decide", "--state", "a ticket text", "--questions", q)[1]
    assert text["state"] == "a ticket text" and isinstance(text["questions"], dict)
    obj = parse(tools, "decide", "--state", '{"a": 1}', "--questions", q)[1]
    assert obj["state"] == {"a": 1}
    number = parse(tools, "decide", "--state", "123", "--questions", q)[1]
    assert number["state"] == "123"  # JSON numbers stay text


def test_args_json_merges_first_and_flags_win(tools):
    ns, args = parse(
        tools,
        "decide",
        "--args-json",
        json.dumps({"state": "from json", "questions": {"u": {"type": "noul"}}}),
        "--state",
        "from flag",
    )
    assert args["state"] == "from flag" and args["questions"] == {"u": {"type": "noul"}}
    assert parse(tools, "ask", "--args-json", '{"query": "q", "depth": "low"}')[1] == {
        "query": "q",
        "depth": "low",
    }


def test_a_required_value_still_missing_exits_2_naming_it(tools, capsys):
    assert "query" in refused(tools, capsys, "ask")
    assert "state" in refused(tools, capsys, "decide", "--questions", "{}")
    assert "action" in refused(tools, capsys, "chat")


def test_wrong_types_unknown_and_abbreviated_flags_exit_2(tools, capsys):
    assert "--max-results" in refused(tools, capsys, "search", "q", "--max-results", "many")
    assert "--bogus" in refused(tools, capsys, "ask", "q", "--bogus", "1")
    err = refused(tools, capsys, "ask", "q", "--dom", "a.com")  # abbreviation of --domains
    assert "--dom" in err


def test_a_bad_json_value_is_refused_naming_the_flag(tools, capsys):
    assert "--json-schema" in refused(tools, capsys, "ask", "q", "--json-schema", "{not json")
    assert "--args-json" in refused(tools, capsys, "ask", "--args-json", "[1]")


def test_the_two_schema_enums_are_refused_locally(tools, capsys):
    enums = {t.command: [n for n, s in t.properties.items() if command._choices(s)] for t in tools}
    assert enums["usage"] == ["group_by"] and enums["projects"] == ["action"]
    assert "invalid choice" in refused(tools, capsys, "usage", "--group-by", "hour")
    assert "invalid choice" in refused(tools, capsys, "projects", "explode")


def test_a_described_value_reaches_the_tool(tools):
    assert parse(tools, "ask", "q", "--depth", "turbo")[1]["depth"] == "turbo"  # the tool refuses


def test_a_parameter_added_to_a_tool_becomes_a_flag(tools):
    ask = next(t for t in tools if t.name == "perplexity_ask")
    schema = json.loads(json.dumps(ask.schema))
    schema["properties"]["brand_new"] = {"type": "boolean", "description": "Added later"}
    changed = [
        ToolSpec(t.name, t.command, schema if t is ask else t.schema, t.annotations) for t in tools
    ]
    ns, args = parse(changed, "ask", "q", "--brand-new")
    assert args["brand_new"] is True
    parser = build_parser(changed)
    helptext = parser._subparsers._group_actions[0].choices["ask"].format_help()
    assert "--brand-new" in helptext and "Added later" in helptext


def test_every_real_parameter_has_a_flag_or_is_positional(tools):
    parser = build_parser(tools)
    choices = parser._subparsers._group_actions[0].choices
    for t in tools:
        if t.name == "perplexity_help":
            continue
        text = choices[t.command].format_help()
        for name in t.properties:
            assert command.flag_name(name) in text or name in ("action", "query"), (t.name, name)


def test_building_the_parser_needs_no_key_no_network_no_files(tmp_path):
    code = (
        "import socket, sys\n"
        "def boom(*a, **k): raise AssertionError('network')\n"
        "socket.socket.connect = boom\n"
        "from mcp_perplexity_pro.command import schema_source, build_parser\n"
        "build_parser(schema_source())\n"
        "print('ok')\n"
    )
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PERPLEXITY_")}
    env.update(HOME=str(home), PERPLEXITY_DATA_DIR=str(tmp_path / "data"))
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True, cwd=tmp_path
    )
    assert result.returncode == 0 and "ok" in result.stdout, result.stderr
    assert not (tmp_path / "data").exists()
    assert list(home.iterdir()) == [] and list(tmp_path.iterdir()) == [home]


def test_an_invalid_environment_still_builds_the_parser(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_PORT", "nope")
    settings, warning = command.settings_for_help()
    assert warning and settings.port == 8102


_ = socket  # the guard in conftest forbids connections during these tests

"""py-cli task 2.1: running a command in-process over a mock transport (cli spec)."""

import json
import sqlite3
import sys

import httpx2
import pytest
from agent_support import fixture

from mcp_perplexity_pro import command
from mcp_perplexity_pro.command import main

TIERS = {
    "PERPLEXITY_TIER_LIGHT": "x/light",
    "PERPLEXITY_TIER_STANDARD": "x/standard",
    "PERPLEXITY_TIER_COMPLEX": "x/complex",
}


@pytest.fixture
def env(monkeypatch, tmp_path):
    for name in list(__import__("os").environ):
        if name.startswith("PERPLEXITY_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-dummy-api-key")
    monkeypatch.setenv("PERPLEXITY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PERPLEXITY_MAX_ATTEMPTS", "1")
    return tmp_path / "data"


class Upstream:
    def __init__(self, body=None, status=200):
        self.requests = []
        self.body = body if body is not None else fixture("agent_fast.json")
        self.status = status

    def client(self):
        def handler(request):
            self.requests.append(json.loads(request.content) if request.content else None)
            return httpx2.Response(self.status, json=self.body)

        return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def events(data_dir):
    with sqlite3.connect(data_dir / "perplexity.db") as db:
        return db.execute("SELECT tool, api, status, preset, model FROM usage_events").fetchall()


def test_text_output_is_the_answer_and_one_usage_event_is_recorded(env, capsys):
    up = Upstream()
    assert main(["ask", "q"], http=up.client()) == 0
    out = capsys.readouterr()
    assert "Python" in out.out and "Usage:" in out.out
    assert out.err == ""  # stdout is the answer, stderr has no log lines
    assert len(up.requests) == 1 and up.requests[0]["model"] == "perplexity/sonar"
    assert events(env) == [
        ("perplexity_ask", "agent", "ok", None, fixture("agent_fast.json")["model"])
    ]


def test_json_output_is_one_document_equal_to_the_structured_result(env, capsys):
    assert main(["ask", "q", "--depth", "fast", "--json"], http=Upstream().client()) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "completed" and doc["depth"] == "fast"
    assert doc["routing"]["selected_by"] == "depth" and doc["usage"]["cost_usd"] == "0.00125"


def test_a_tool_error_prints_category_and_the_cli_help_sentence_and_exits_1(env, capsys):
    up = Upstream()
    assert main(["ask", "q", "--depth", "high"], http=up.client()) == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.startswith("[invalid_request] depth:")
    assert out.err.rstrip().endswith("Run perplexity-pro help ask for its arguments and examples.")
    assert "perplexity_help" not in out.err
    assert up.requests == []
    assert not (env / "perplexity.db").exists() or events(env) == []


def test_an_upstream_failure_keeps_its_category_without_a_hint(env, capsys):
    up = Upstream(body={"error": {"message": "slow", "type": "rate_limit"}}, status=429)
    assert main(["ask", "q"], http=up.client()) == 1
    err = capsys.readouterr().err
    assert err.startswith("[rate_limited]") and "Run perplexity-pro help" not in err


def test_a_missing_key_exits_1_naming_it_and_creates_nothing(monkeypatch, tmp_path, capsys):
    for name in list(__import__("os").environ):
        if name.startswith("PERPLEXITY_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PERPLEXITY_DATA_DIR", str(tmp_path / "data"))
    with pytest.raises(SystemExit) as info:
        main(["models"], http=Upstream().client())
    assert info.value.code == 1
    assert "PERPLEXITY_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()


def test_routing_applies_in_custom_mode_with_tier(env, monkeypatch, capsys):
    monkeypatch.setenv("PERPLEXITY_ROUTING", "custom")
    for name, value in TIERS.items():
        monkeypatch.setenv(name, value)
    up = Upstream()
    assert main(["ask", "q", "--tier", "light", "--json"], http=up.client()) == 0
    assert up.requests[0]["model"] == "x/light"
    assert json.loads(capsys.readouterr().out)["routing"]["tier"] == "light"


def test_two_selectors_are_refused_by_the_tool_and_nothing_is_sent(env, monkeypatch, capsys):
    monkeypatch.setenv("PERPLEXITY_ROUTING", "custom")
    for name, value in TIERS.items():
        monkeypatch.setenv(name, value)
    up = Upstream()
    assert main(["ask", "q", "--tier", "light", "--depth", "low"], http=up.client()) == 1
    assert "cannot be combined" in capsys.readouterr().err and up.requests == []


def test_usage_command_reads_the_same_database(env, capsys):
    main(["ask", "q"], http=Upstream().client())
    capsys.readouterr()
    assert main(["usage", "--json"], http=Upstream().client()) == 0
    assert json.loads(capsys.readouterr().out)["totals"]["calls"] == 1


def test_the_client_and_engine_are_closed_on_success_and_on_error(env, monkeypatch):
    closed = []
    import mcp_perplexity_pro.__main__ as entry

    real = entry.close_resources

    async def spy(server):
        closed.append(server)
        await real(server)

    monkeypatch.setattr(entry, "close_resources", spy)
    main(["ask", "q"], http=Upstream().client())
    main(["ask", "q", "--depth", "high"], http=Upstream().client())
    assert len(closed) == 2


def test_a_closed_pipe_ends_quietly(env, monkeypatch):
    class Broken:
        def isatty(self):
            return False

        def write(self, text):
            raise BrokenPipeError

        def flush(self):
            raise BrokenPipeError

        def fileno(self):
            return sys.__stdout__.fileno() if False else __import__("os").open("/dev/null", 1)

    monkeypatch.setattr(sys, "stdout", Broken())
    assert main(["ask", "q"], http=Upstream().client()) == 0


def test_keyboard_interrupt_exits_130(env, monkeypatch):
    async def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(command, "run_tool", interrupted)
    assert main(["ask", "q"]) == 130


def test_ctrl_c_during_a_call_exits_130_without_a_traceback(tmp_path):
    """A real process, a slow loopback upstream and SIGINT while the call is in flight."""
    import http.server
    import os
    import signal
    import subprocess
    import threading

    arrived = threading.Event()

    class Slow(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the stdlib's name
            arrived.set()
            threading.Event().wait(120)  # longer than the test waits for the process

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PERPLEXITY_")}
    env.update(
        PERPLEXITY_API_KEY="test-dummy-api-key",
        PERPLEXITY_DATA_DIR=str(tmp_path / "data"),
        PERPLEXITY_BASE_URL=f"http://127.0.0.1:{server.server_address[1]}",
        PERPLEXITY_MAX_ATTEMPTS="1",
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_perplexity_pro.command", "ask", "q"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert arrived.wait(30), "the call never reached the upstream"
        proc.send_signal(signal.SIGINT)
        out, err = proc.communicate(timeout=60)
    finally:
        proc.kill()
        server.shutdown()
    assert proc.returncode == 130, (out, err)
    assert "Traceback" not in err and out == ""


def test_an_interrupt_during_the_call_still_closes_the_client_and_engine(env, monkeypatch):
    import fastmcp

    import mcp_perplexity_pro.__main__ as entry

    closed = []
    real = entry.close_resources

    async def spy(server):
        closed.append(True)
        await real(server)

    async def interrupted(self, *args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(entry, "close_resources", spy)
    monkeypatch.setattr(fastmcp.Client, "call_tool", interrupted)
    assert main(["ask", "q"], http=Upstream().client()) == 130
    assert closed == [True]


def test_version_and_serve_help_do_not_build_the_schemas(monkeypatch, capsys):
    def boom():
        raise AssertionError("the schemas were built")

    monkeypatch.setattr(command, "schema_source", boom)
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip()
    with pytest.raises(SystemExit) as info:
        main(["serve", "--help"])
    assert info.value.code == 0 and "--transport" in capsys.readouterr().out


def test_an_ask_in_dynamic_mode_with_the_decisions_classifier_records_two_events(
    env, monkeypatch, capsys
):
    monkeypatch.setenv("PERPLEXITY_ROUTING", "dynamic")
    monkeypatch.setenv("PERPLEXITY_CLASSIFIER", "decisions")
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/v1/decisions":
            return httpx2.Response(200, json=fixture("decisions_tier_light.json"))
        return httpx2.Response(200, json=fixture("agent_fast.json"))

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    assert main(["ask", "What is the latest stable Python release?", "--json"], http=http) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["routing"]["classifier"] == "decisions" and doc["routing"]["tier"] == "light"
    assert seen == ["/v1/decisions", "/v1/agent"]
    assert [(e[0], e[1], e[2]) for e in events(env)] == [
        ("perplexity_ask", "decisions", "ok"),
        ("perplexity_ask", "agent", "ok"),
    ]


# --- model-matrix task 3.1: a one-shot command starts no refresh task ---------------------------


def recording_client(seen, body=None):
    from matrix_support import models_payload

    def handler(request):
        seen.append(request.url.path)
        return httpx2.Response(200, json=body if body is not None else models_payload())

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def test_a_one_shot_command_makes_no_models_request_and_writes_no_matrix(env, capsys):
    from mcp_perplexity_pro import matrix

    seen: list[str] = []
    assert main(["usage", "--json"], http=recording_client(seen)) == 0
    assert seen == []  # nothing upstream: no refresh, and the command itself needs none
    assert not (env / matrix.FILENAME).exists() and not (env / matrix.LOCK_FILENAME).exists()


def test_a_one_shot_models_command_reads_the_stored_matrix_and_writes_nothing(env, capsys):
    from mcp_perplexity_pro import matrix

    env.mkdir(parents=True)
    path = env / matrix.FILENAME
    matrix.write(path, matrix.load_baseline())
    raw, mtime = path.read_bytes(), path.stat().st_mtime_ns
    seen: list[str] = []
    assert main(["models", "--json"], http=recording_client(seen)) == 0
    assert seen == ["/v1/models"]  # the tool's own request, nothing for a matrix refresh
    assert path.read_bytes() == raw and path.stat().st_mtime_ns == mtime
    assert not (env / matrix.LOCK_FILENAME).exists()


def test_the_schema_builder_and_help_touch_no_data_directory(env, capsys):
    assert not env.exists()
    command.schema_source()
    assert not env.exists()
    assert main(["help"], http=recording_client([])) == 0
    assert not env.exists()

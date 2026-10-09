"""Server runtime: transports, /health, version source, stdio protocol hygiene."""

import json
import shutil
import socket
import subprocess
import tomllib
from importlib.metadata import version
from pathlib import Path

import httpx2
import pytest
from server_support import (
    free_port,
    listening_ports,
    read_message,
    rpc,
    send,
    serving,
    start_fixture_server,
    stdio_initialize,
)

from mcp_perplexity_pro.__main__ import build_http_server
from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

ROOT = Path(__file__).parent.parent


@pytest.fixture
def upstream_calls():
    return []


@pytest.fixture
async def make_server(make_settings, upstream_calls):
    """Build the real server on a migrated temp database; the upstream records any request."""
    built = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        upstream_calls.append(request)
        return httpx2.Response(500, json={"error": {"message": "no upstream in this test"}})

    async def factory(**overrides):
        settings = make_settings(**overrides)
        migrate(settings)
        engine = create_engine_for(settings)
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        server = build_server(settings, http, engine)
        built.append((http, engine))
        return server, settings

    yield factory
    for http, engine in built:
        await http.aclose()
        await engine.dispose()


async def test_health_is_ok_without_any_upstream_call(make_server, upstream_calls):
    server, settings = await make_server()
    app = server.http_app(stateless_http=True, json_response=True, host_origin_protection=True)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": version("mcp-perplexity-pro")}
    assert upstream_calls == []


async def test_versions_agree_across_health_initialize_and_metadata(make_server, make_settings):
    server, settings = await make_server(port=free_port())
    async with serving(server, settings):
        async with httpx2.AsyncClient() as client:
            base = f"http://127.0.0.1:{settings.port}"
            health = (await client.get(f"{base}/health")).json()["version"]
            init = await rpc(client, f"{base}/mcp", "initialize", _initialize_params())
    initialize = init["result"]["serverInfo"]["version"]
    metadata = version("mcp-perplexity-pro")
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    # ``declared`` catches a stale editable install after a version bump: re-run ``uv sync``.
    assert health == initialize == metadata == declared


def _initialize_params():
    from server_support import INITIALIZE

    return INITIALIZE


async def test_initialize_over_http_lists_registered_tools(make_server):
    server, settings = await make_server(port=free_port())

    @server.tool
    def ping() -> str:
        return "pong"

    async with serving(server, settings):
        async with httpx2.AsyncClient() as client:
            url = f"http://127.0.0.1:{settings.port}/mcp"
            init = await rpc(client, url, "initialize", _initialize_params())
            tools = await rpc(client, url, "tools/list")
    assert init["result"]["serverInfo"]["name"] == "perplexity-pro"
    names = [t["name"] for t in tools["result"]["tools"]]
    # production tools exist from construction
    assert sorted(names) == ["perplexity_models", "perplexity_projects", "perplexity_usage", "ping"]


async def test_defaults_are_loopback_8102_without_binding(make_server):
    server, settings = await make_server()  # defaults: no host or port override
    assert (settings.host, settings.port) == ("127.0.0.1", 8102)
    config = build_http_server(server, settings).config  # constructed, never served
    assert (config.host, config.port) == ("127.0.0.1", 8102)


async def test_http_runner_drains_for_the_ten_second_bound(make_server):
    server, settings = await make_server()
    assert build_http_server(server, settings).config.timeout_graceful_shutdown == 10


async def test_port_override_listens_only_on_the_override(make_server):
    port = free_port()
    server, settings = await make_server(port=port)
    async with serving(server, settings) as uv:
        assert listening_ports(uv) == {port}
        assert 8102 not in listening_ports(uv)
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass


def _lan_address() -> str | None:
    """This host's outbound non-loopback IPv4 address (a UDP connect sends nothing)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.0.2.1", 9))  # TEST-NET-1: a route lookup only, no packet is sent
            address = sock.getsockname()[0]
        except OSError:
            return None
    return None if address.startswith("127.") or address == "0.0.0.0" else address


@pytest.mark.allow_network
async def test_default_host_refuses_the_lan_address(make_server):
    lan = _lan_address()
    if lan is None:
        pytest.skip("this host has no non-loopback IPv4 address")
    port = free_port()
    server, settings = await make_server(port=port)
    assert settings.host == "127.0.0.1"
    async with serving(server, settings):
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass  # loopback is accepted
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection((lan, port), timeout=2)


def _listening_sockets(pid: int) -> str | None:
    """lsof output for ``pid``'s listening TCP sockets, or None when lsof is unavailable."""
    if shutil.which("lsof") is None:
        return None
    result = subprocess.run(
        ["lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return result.stdout.strip()


def test_stdio_mode_completes_initialize_and_opens_no_listener(tmp_path):
    proc = start_fixture_server(tmp_path, "stdio")
    try:
        reply = stdio_initialize(proc)
        assert reply["result"]["serverInfo"]["name"] == "perplexity-pro"
        listeners = _listening_sockets(proc.pid)
        if listeners is None:
            pytest.skip("lsof is not available to inspect sockets")
        assert listeners == ""
    finally:
        proc.stdin.close()
        proc.wait(timeout=20)
        proc.stdout.close()
        proc.stderr.close()


def test_stdio_stdout_is_only_protocol_and_logs_go_to_stderr(tmp_path):
    proc = start_fixture_server(tmp_path, "stdio", PERPLEXITY_LOG_LEVEL="DEBUG")
    try:
        stdio_initialize(proc)
        send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "log_all", "arguments": {}},
            },
        )
        reply = read_message(proc)
        assert reply["id"] == 2 and not reply["result"].get("isError")
        proc.stdin.close()
        rest = proc.stdout.read()
        stderr = proc.stderr.read()
        proc.wait(timeout=20)
    finally:
        proc.kill()
        proc.stdout.close()
        proc.stderr.close()
    for line in rest.splitlines():  # anything left on stdout must also be JSON-RPC
        assert json.loads(line)["jsonrpc"] == "2.0"
    for level_line in ("debug", "info", "warning", "error", "critical"):
        assert f"fixture-{level_line}-line" in stderr
    assert "fixture-" not in rest and "fixture-" not in json.dumps(reply)

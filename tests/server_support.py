"""Helpers for server tests: ephemeral ports, an in-process listener, JSON-RPC calls and a
subprocess launcher for ``tests/fixture_server.py``."""

import asyncio
import json
import os
import socket
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2

FIXTURE_SERVER = Path(__file__).parent / "fixture_server.py"
PROTOCOL = "2025-06-18"
INITIALIZE = {
    "protocolVersion": PROTOCOL,
    "capabilities": {},
    "clientInfo": {"name": "pytest", "version": "0"},
}
HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": PROTOCOL,
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def rpc(http: httpx2.AsyncClient, url: str, method: str, params: dict | None = None):
    """POST one JSON-RPC request to a stateless ``/mcp`` endpoint and return the JSON body."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    response = await http.post(url, json=body, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


@asynccontextmanager
async def serving(server, settings):
    """Run the real HTTP runner in-process; yields the ``uvicorn.Server`` once it is listening."""
    from mcp_perplexity_pro.__main__ import build_http_server

    uv = build_http_server(server, settings)
    task = asyncio.create_task(uv.serve())
    try:
        for _ in range(500):
            if uv.started or task.done():
                break
            await asyncio.sleep(0.01)
        assert uv.started, "server did not start"
        yield uv
    finally:
        uv.should_exit = True
        await asyncio.wait_for(task, 15)


def listening_ports(uv) -> set[int]:
    return {sock.getsockname()[1] for srv in uv.servers for sock in srv.sockets}


def server_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """A minimal environment for a subprocess server: loopback-only upstream, temp data/home."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path / "home"),
        "PERPLEXITY_API_KEY": "test-dummy-api-key",
        "PERPLEXITY_DATA_DIR": str(tmp_path / "data"),
        "PERPLEXITY_BASE_URL": "http://127.0.0.1:9",  # nothing listens; never leaves the host
    }
    env.update(extra)
    (tmp_path / "home").mkdir(exist_ok=True)
    return env


def start_fixture_server(tmp_path: Path, transport: str, **extra_env: str) -> subprocess.Popen:
    """Start ``fixture_server.py`` (the real ``build_server`` + ``run`` plus test tools)."""
    return subprocess.Popen(
        [sys.executable, str(FIXTURE_SERVER), transport],
        env=server_env(tmp_path, **extra_env),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def send(proc: subprocess.Popen, message: dict) -> None:
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()


def read_message(proc: subprocess.Popen) -> dict:
    line = proc.stdout.readline()
    assert line, "server closed stdout"
    return json.loads(line)


def stdio_initialize(proc: subprocess.Popen) -> dict:
    send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INITIALIZE})
    reply = read_message(proc)
    send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    return reply


def wait_for_http(port: int, proc: subprocess.Popen, timeout: float = 20) -> None:
    """Block until ``GET /health`` answers on ``port`` (or fail with the process's stderr)."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"server exited early ({proc.returncode}): {proc.stderr.read()}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("server did not start listening")

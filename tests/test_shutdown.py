"""Graceful shutdown, proved on real subprocesses: exit status, closures logged, in-flight calls."""

import asyncio
import signal
import time

import httpx2
import pytest
from server_support import (
    INITIALIZE,
    StderrTail,
    free_port,
    read_message,
    rpc,
    send,
    start_fixture_server,
    stdio_initialize,
    wait_for_http,
)

from mcp_perplexity_pro import __main__ as entry

CLOSURES = ("http client closed", "engine disposed")
SIGNALS = [pytest.param(signal.SIGTERM, id="SIGTERM"), pytest.param(signal.SIGINT, id="SIGINT")]


def assert_clean_exit(proc, tail, within=5.0):
    started = time.monotonic()
    code = proc.wait(timeout=within)
    stderr = tail.text()
    assert code == 0, f"exit status {code}\n{stderr}"
    assert time.monotonic() - started < within
    for line in CLOSURES:
        assert line in stderr, f"{line!r} missing from stderr:\n{stderr}"
    # The log lines alone would survive a deleted close call; this file is written only when
    # the real ``aclose()`` / ``dispose()`` ran to completion.
    assert sorted(proc.close_log.read_text().split()) == ["engine.dispose", "http.aclose"]
    return stderr


def test_the_stop_bound_is_ten_seconds():
    assert entry.GRACEFUL_TIMEOUT == 10


@pytest.mark.parametrize("sig", SIGNALS)
def test_http_idle_signal_exits_zero_and_logs_both_closures(tmp_path, sig):
    port = free_port()
    proc = start_fixture_server(tmp_path, "http", PERPLEXITY_PORT=str(port))
    tail = StderrTail(proc)
    wait_for_http(port, proc)
    proc.send_signal(sig)
    assert_clean_exit(proc, tail)


@pytest.mark.parametrize("sig", SIGNALS)
def test_stdio_idle_signal_exits_zero_and_logs_both_closures(tmp_path, sig):
    proc = start_fixture_server(tmp_path, "stdio")
    tail = StderrTail(proc)
    stdio_initialize(proc)
    proc.send_signal(sig)
    assert_clean_exit(proc, tail)


def test_stdin_eof_in_stdio_mode_exits_zero_and_logs_both_closures(tmp_path):
    proc = start_fixture_server(tmp_path, "stdio")
    tail = StderrTail(proc)
    stdio_initialize(proc)
    proc.stdin.close()
    assert_clean_exit(proc, tail)


async def _nap_over_http(port: int, seconds: float):
    async with httpx2.AsyncClient(timeout=30) as client:
        url = f"http://127.0.0.1:{port}/mcp"
        await rpc(client, url, "initialize", INITIALIZE)
        return await rpc(
            client, url, "tools/call", {"name": "nap", "arguments": {"seconds": seconds}}
        )


async def test_http_in_flight_call_finishing_in_time_returns_before_exit(tmp_path):
    port = free_port()
    proc = start_fixture_server(tmp_path, "http", PERPLEXITY_PORT=str(port))
    tail = StderrTail(proc)
    await asyncio.to_thread(wait_for_http, port, proc)
    call = asyncio.create_task(_nap_over_http(port, 0.8))
    await asyncio.to_thread(tail.wait_for, "nap started")
    proc.send_signal(signal.SIGTERM)
    reply = await call  # delivered although SIGTERM arrived while the call was running
    assert reply["result"]["structuredContent"]["result"] == "rested"
    await asyncio.to_thread(assert_clean_exit, proc, tail)


async def test_http_in_flight_call_that_outlives_the_bound_is_cut_off(tmp_path):
    port = free_port()
    proc = start_fixture_server(
        tmp_path, "http", PERPLEXITY_PORT=str(port), FIXTURE_GRACEFUL_TIMEOUT="0.5"
    )
    tail = StderrTail(proc)
    await asyncio.to_thread(wait_for_http, port, proc)
    call = asyncio.create_task(_nap_over_http(port, 60))
    await asyncio.to_thread(tail.wait_for, "nap started")
    proc.send_signal(signal.SIGTERM)
    started = time.monotonic()
    await asyncio.to_thread(assert_clean_exit, proc, tail, 8)
    assert time.monotonic() - started < 8  # nowhere near the 60 s the call wanted
    with pytest.raises((AssertionError, httpx2.HTTPError)):
        await call  # the client got an error or a dropped connection, not a result


def _call_nap_stdio(proc, seconds: float) -> None:
    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "nap", "arguments": {"seconds": seconds}},
        },
    )


def test_stdio_in_flight_call_finishing_in_time_returns_before_exit(tmp_path):
    proc = start_fixture_server(tmp_path, "stdio")
    tail = StderrTail(proc)
    stdio_initialize(proc)
    _call_nap_stdio(proc, 0.6)
    tail.wait_for("nap started")
    proc.send_signal(signal.SIGTERM)
    reply = read_message(proc)
    assert reply["id"] == 7 and reply["result"]["structuredContent"]["result"] == "rested"
    assert_clean_exit(proc, tail)


def test_stdio_in_flight_call_that_outlives_the_bound_is_cut_off(tmp_path):
    proc = start_fixture_server(tmp_path, "stdio", FIXTURE_GRACEFUL_TIMEOUT="0.5")
    tail = StderrTail(proc)
    stdio_initialize(proc)
    _call_nap_stdio(proc, 60)
    tail.wait_for("nap started")
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    stderr = assert_clean_exit(proc, tail, 8)
    assert time.monotonic() - started < 8
    assert "cutting them off" in stderr


def test_stdio_refuses_new_calls_while_draining(tmp_path):
    proc = start_fixture_server(tmp_path, "stdio")
    tail = StderrTail(proc)
    stdio_initialize(proc)
    _call_nap_stdio(proc, 0.8)
    tail.wait_for("nap started")
    proc.send_signal(signal.SIGTERM)
    tail.wait_for("shutdown: waiting")
    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "nap", "arguments": {"seconds": 0}},
        },
    )
    replies = {}
    for _ in range(2):
        message = read_message(proc)
        replies[message["id"]] = message["result"]
    assert replies[8]["isError"] is True
    assert replies[8]["structuredContent"]["category"] == "internal_error"
    assert replies[7]["structuredContent"]["result"] == "rested"  # the running call still finishes
    assert_clean_exit(proc, tail)


def _tree(root):
    """Every path under ``root`` relative to it (platform-neutral; includes directories)."""
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_nothing_is_written_outside_the_data_directory(tmp_path, transport):
    """With an empty HOME, working directory and TMPDIR, a full run touches only the data dir."""
    for name in ("cwd", "tmp"):
        (tmp_path / name).mkdir()
    port = free_port()
    proc = start_fixture_server(
        tmp_path,
        transport,
        cwd=tmp_path / "cwd",
        TMPDIR=str(tmp_path / "tmp"),
        PERPLEXITY_PORT=str(port),
    )
    tail = StderrTail(proc)
    if transport == "stdio":
        stdio_initialize(proc)
        send(
            proc,
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "log_all", "arguments": {}}},
        )  # fmt: skip
        read_message(proc)
        proc.stdin.close()
    else:
        wait_for_http(port, proc)
        with httpx2.Client() as client:
            assert client.get(f"http://127.0.0.1:{port}/health").status_code == 200
        proc.send_signal(signal.SIGTERM)
    assert_clean_exit(proc, tail)
    assert _tree(tmp_path / "home") == []  # nothing under the (empty) home directory
    assert _tree(tmp_path / "cwd") == []
    assert _tree(tmp_path / "tmp") == []
    assert (tmp_path / "data" / "perplexity.db").exists()  # the one place it does write

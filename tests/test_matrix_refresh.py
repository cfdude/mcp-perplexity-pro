"""model-matrix task 3.1: the refresh task, its settings, its lifecycle and its shutdown.

The loop is driven directly (``run_refresh``) where a scenario is about what one refresh does, and
through the real HTTP runner (``serving``) or a subprocess (``tests/fixture_server.py``) where it
is about start, shutdown and not blocking.
"""

import asyncio
import json
import logging
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx2
import pytest
from agent_support import fixture
from matrix_support import MatrixWorld, Upstream, make_matrix_world, models_payload, payload_with
from server_support import (
    INITIALIZE,
    StderrTail,
    free_port,
    rpc,
    serving,
    start_fixture_server,
    stdio_initialize,
    wait_for_http,
)

from mcp_perplexity_pro import __main__ as entry
from mcp_perplexity_pro import matrix, matrix_refresh
from mcp_perplexity_pro.settings import SettingsError, load_settings

KEY = "test-dummy-api-key"
LOGGER = "mcp_perplexity_pro.matrix_refresh"


@pytest.fixture
async def worlds(make_settings):
    made: list[MatrixWorld] = []

    async def factory(upstream: Upstream | None = None, **kwargs) -> MatrixWorld:
        world = await make_matrix_world(make_settings, upstream or Upstream(), **kwargs)
        made.append(world)
        return world

    yield factory
    for world in made:
        await world.aclose()


def path_of(world: MatrixWorld) -> Path:
    return world.settings.data_dir / matrix.FILENAME


def warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


async def until(predicate, timeout=10.0):
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the condition never held")


# --- settings ---------------------------------------------------------------------------------


@pytest.fixture
def key_env(monkeypatch):
    for name in list(os.environ):
        if name.upper().startswith("PERPLEXITY_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PERPLEXITY_API_KEY", KEY)


def test_the_matrix_settings_default_to_a_day_and_new(key_env):
    s = load_settings()
    assert s.matrix_refresh == 86400 and s.matrix_probe == "new"


@pytest.mark.parametrize("value", ["0", "300", "86400", "604800"])
def test_a_refresh_interval_of_zero_or_300_to_604800_is_accepted(key_env, monkeypatch, value):
    monkeypatch.setenv("PERPLEXITY_MATRIX_REFRESH", value)
    assert load_settings().matrix_refresh == int(value)


@pytest.mark.parametrize("value", ["60", "299", "604801", "-1", "abc", "1.5", ""])
def test_a_bad_refresh_interval_fails_naming_the_variable_and_the_range(
    key_env, monkeypatch, value
):
    monkeypatch.setenv("PERPLEXITY_MATRIX_REFRESH", value)
    with pytest.raises(SettingsError) as info:
        load_settings()
    text = str(info.value)
    assert "PERPLEXITY_MATRIX_REFRESH" in text
    assert KEY not in text
    if value.lstrip("-").isdigit():  # a number out of range names the accepted range
        assert "300" in text and "604800" in text


@pytest.mark.parametrize("value,expected", [("new", "new"), ("OFF", "off"), (" Off ", "off")])
def test_the_probe_setting_is_case_insensitive(key_env, monkeypatch, value, expected):
    monkeypatch.setenv("PERPLEXITY_MATRIX_PROBE", value)
    assert load_settings().matrix_probe == expected


def test_a_bad_probe_value_fails_naming_the_variable_and_the_values(key_env, monkeypatch):
    monkeypatch.setenv("PERPLEXITY_MATRIX_PROBE", "sometimes")
    with pytest.raises(SettingsError) as info:
        load_settings()
    text = str(info.value)
    assert "PERPLEXITY_MATRIX_PROBE" in text and "new" in text and "off" in text


# --- the state: lazy first read, never a write ------------------------------------------------


async def test_the_matrix_is_loaded_lazily_on_the_first_snapshot_and_never_written(worlds):
    world = await worlds(refresh_task=False)
    state = world.app.matrix
    before = sorted(p.name for p in world.settings.data_dir.iterdir())
    assert state._loaded is None  # nothing read at construction
    first = state.snapshot()
    assert first.origin == "baseline" and first.state == "missing"
    assert state.snapshot() is first  # read once
    assert sorted(p.name for p in world.settings.data_dir.iterdir()) == before  # nothing written


async def test_a_stored_file_is_read_with_origin_file_without_modifying_it(worlds):
    world = await worlds(refresh_task=False)
    stored = matrix.load_baseline()
    matrix.write(path_of(world), stored)
    raw, mtime = path_of(world).read_bytes(), path_of(world).stat().st_mtime_ns
    snap = world.app.matrix.snapshot()
    assert snap.origin == "file" and set(snap.matrix.models) == set(stored.models)
    assert path_of(world).read_bytes() == raw and path_of(world).stat().st_mtime_ns == mtime
    assert not (world.settings.data_dir / matrix.LOCK_FILENAME).exists()


# --- what one refresh does --------------------------------------------------------------------


async def test_a_refresh_writes_the_live_list_into_the_file_and_the_state(worlds, caplog):
    world = await worlds(refresh_task=False, matrix_refresh=0)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await matrix_refresh.run_refresh(world.app)  # interval 0: once, then returns
    assert world.upstream.count("/v1/models") == 1
    stored = matrix.load(path_of(world))
    assert stored.state == "ok" and stored.origin == "file"
    assert set(stored.matrix.models) == {m["id"] for m in models_payload()["data"]}
    assert (path_of(world).stat().st_mode & 0o777) == 0o600
    assert world.app.matrix.snapshot().origin == "file"  # the state adopted what was written
    assert warnings(caplog) == []


async def test_the_start_logs_one_info_line_naming_the_settings_and_the_origin(worlds, caplog):
    world = await worlds(refresh_task=False, matrix_refresh=0, matrix_probe="off")
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await matrix_refresh.run_refresh(world.app)
    started = [r.getMessage() for r in caplog.records if "started" in r.getMessage()]
    assert len(started) == 1
    assert "refresh=0" in started[0] and "probe=off" in started[0] and "baseline" in started[0]


async def test_a_500_with_a_fresh_catalog_cache_warns_once_and_leaves_the_file(worlds, caplog):
    world = await worlds(refresh_task=False, matrix_refresh=0)
    await world.app.catalog.get()  # a fresh list is cached now
    matrix.write(path_of(world), matrix.load_baseline())
    raw, mtime = path_of(world).read_bytes(), path_of(world).stat().st_mtime_ns
    world.upstream.models_status = 500
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await matrix_refresh.run_refresh(world.app)
    assert world.upstream.count("/v1/models") == 2  # the refresh bypassed the cache
    assert path_of(world).read_bytes() == raw and path_of(world).stat().st_mtime_ns == mtime
    assert len(warnings(caplog)) == 1  # the stale list the catalog returned was not merged


async def test_a_failing_models_endpoint_never_escapes_the_task(worlds, caplog):
    world = await worlds(Upstream(models_status=500), refresh_task=False, matrix_refresh=0)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await matrix_refresh.run_refresh(world.app)
    assert len(warnings(caplog)) == 1 and not path_of(world).exists()


async def test_any_exception_in_a_refresh_is_one_redacted_warning_never_an_escape(
    worlds, caplog, monkeypatch
):
    world = await worlds(refresh_task=False, matrix_refresh=0)

    def boom(*_args, **_kwargs):
        raise RuntimeError(f"merge exploded (key {KEY})")

    monkeypatch.setattr(matrix, "merge", boom)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await matrix_refresh.run_refresh(world.app)  # must return, not raise
    (record,) = warnings(caplog)
    assert "merge exploded" in record.getMessage() and KEY not in record.getMessage()
    assert not path_of(world).exists()


async def test_the_interval_refreshes_again_bypassing_the_cache_through_an_injected_sleep(worlds):
    world = await worlds(refresh_task=False, matrix_refresh=300)
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 3:
            raise asyncio.CancelledError  # ends the endless loop after three intervals

    world.app.matrix.sleep = fake_sleep
    with pytest.raises(asyncio.CancelledError):
        await matrix_refresh.run_refresh(world.app)
    assert slept == [300, 300, 300]
    assert (
        world.upstream.count("/v1/models") == 3
    )  # 3600 s cache, one at start and one per interval


async def test_an_interval_of_zero_refreshes_once_and_never_sleeps(worlds):
    world = await worlds(refresh_task=False, matrix_refresh=0)

    async def no_sleep(_seconds: float) -> None:
        raise AssertionError("slept")

    world.app.matrix.sleep = no_sleep
    await matrix_refresh.run_refresh(world.app)
    assert world.upstream.count("/v1/models") == 1


# --- the task in a serving process ------------------------------------------------------------


async def test_the_task_starts_with_the_real_runner_once_and_stops_with_it(worlds):
    world = await worlds(refresh_task=True, port=free_port())
    url = f"http://127.0.0.1:{world.settings.port}/mcp"
    async with serving(world.server, world.settings):
        await until(lambda: path_of(world).exists())
        async with httpx2.AsyncClient() as client:
            await rpc(client, url, "initialize", INITIALIZE)
            for _ in range(3):
                await rpc(client, url, "tools/call", {"name": "perplexity_usage", "arguments": {}})
        task = world.app.matrix.task
        assert task is not None and not task.done()  # the interval is a day: it sleeps
    assert task.done()  # the lifespan cancelled and awaited it
    assert world.upstream.count("/v1/models") == 1  # one task, not one per request


async def test_startup_does_not_wait_for_the_models_endpoint(worlds):
    gate = asyncio.Event()
    world = await worlds(Upstream(gate=gate), refresh_task=True, port=free_port())
    url = f"http://127.0.0.1:{world.settings.port}/mcp"
    try:
        async with serving(world.server, world.settings):  # listening although it is held
            await until(lambda: world.upstream.count("/v1/models") == 1)  # the task did start
            async with httpx2.AsyncClient() as client:
                await rpc(client, url, "initialize", INITIALIZE)
                reply = await rpc(
                    client, url, "tools/call", {"name": "perplexity_usage", "arguments": {}}
                )
            assert "result" in reply and not reply["result"].get("isError")
            assert not gate.is_set() and not path_of(world).exists()  # still the baseline
            assert world.app.matrix.snapshot().origin == "baseline"
            gate.set()
            await until(lambda: path_of(world).exists())
    finally:
        gate.set()


async def test_a_world_built_without_the_flag_starts_no_task_even_under_the_runner(worlds):
    world = await worlds(refresh_task=False, port=free_port())
    async with serving(world.server, world.settings):
        await asyncio.sleep(0.2)
    assert world.app.matrix.task is None
    assert world.upstream.count("/v1/models") == 0 and not path_of(world).exists()


async def test_close_resources_cancels_and_awaits_the_task_before_the_client_closes(worlds):
    gate = asyncio.Event()
    world = await worlds(Upstream(gate=gate), refresh_task=True)
    seen: dict[str, bool] = {}
    real_aclose = world.http.aclose

    async def aclose():
        seen["task_done_at_close"] = world.app.matrix.task.done()
        await real_aclose()

    world.http.aclose = aclose
    matrix_refresh.start_task(world.app)
    await until(lambda: world.upstream.count("/v1/models") == 1)
    try:
        await entry.close_resources(world.server)
    finally:
        gate.set()
    assert seen == {"task_done_at_close": True}
    assert world.app.matrix.task.cancelled()


async def test_close_resources_tolerates_a_server_that_never_started_a_task(worlds):
    world = await worlds(refresh_task=False)
    assert world.app.matrix.task is None
    await entry.close_resources(world.server)  # no task: no error


async def test_stopping_twice_is_harmless(worlds):
    world = await worlds(Upstream(gate=asyncio.Event()), refresh_task=True)
    matrix_refresh.start_task(world.app)
    await matrix_refresh.stop_task(world.app.matrix)
    await matrix_refresh.stop_task(world.app.matrix)
    assert world.app.matrix.task.cancelled()
    world.upstream.gate.set()


# --- who sets the flag ------------------------------------------------------------------------


@pytest.fixture
def boot_env(key_env, monkeypatch, tmp_path):
    monkeypatch.setenv("PERPLEXITY_DATA_DIR", str(tmp_path / "data"))


async def test_only_a_serving_bootstrap_sets_the_flag(boot_env):
    serving_server, _ = entry.bootstrap()
    oneshot_server, _ = entry.bootstrap(serving=False)
    try:
        assert serving_server.app.matrix.enabled is True
        assert oneshot_server.app.matrix.enabled is False
    finally:
        for server in (serving_server, oneshot_server):
            await server.app.http.aclose()
            await server.app.engine.dispose()


def test_serve_and_main_use_the_serving_bootstrap(boot_env, monkeypatch):
    from mcp_perplexity_pro import command

    calls = []

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return object(), object()

    monkeypatch.setattr(entry, "bootstrap", spy)
    monkeypatch.setattr(entry, "run", lambda *a, **k: None)
    command.serve("stdio")
    entry.main(["--transport", "stdio"])
    assert calls == [{}, {}]  # bootstrap() with its default serving=True, both times


# --- shutdown in the middle of a write, on a real process -------------------------------------


class _Models(BaseHTTPRequestHandler):
    body = json.dumps(models_payload()).encode()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args):  # keep the test output clean
        pass


@pytest.fixture
def loopback_models():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Models)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def assert_matrix_whole(tmp_path: Path) -> None:
    """The file is absent (the old state) or a complete, valid matrix (the new one)."""
    path = tmp_path / "data" / matrix.FILENAME
    if path.exists():
        loaded = matrix.load(path)
        assert loaded.state == "ok", "the matrix file is not whole"


def clean_exit(proc, tail, within=6.0):
    assert proc.wait(timeout=within) == 0, tail.text()
    return tail.text()


def test_http_shutdown_in_the_middle_of_a_write_leaves_a_whole_file(tmp_path, loopback_models):
    port = free_port()
    proc = start_fixture_server(
        tmp_path,
        "http",
        PERPLEXITY_PORT=str(port),
        PERPLEXITY_BASE_URL=loopback_models,
        FIXTURE_SLOW_MATRIX_WRITE="1.5",
    )
    tail = StderrTail(proc)
    wait_for_http(port, proc)
    tail.wait_for("matrix write begun")
    proc.send_signal(signal.SIGTERM)
    stderr = clean_exit(proc, tail)
    assert "http client closed" in stderr
    assert_matrix_whole(tmp_path)


@pytest.mark.parametrize("how", ["signal", "eof"])
def test_stdio_shutdown_in_the_middle_of_a_write_leaves_a_whole_file(
    tmp_path, loopback_models, how
):
    proc = start_fixture_server(
        tmp_path,
        "stdio",
        PERPLEXITY_BASE_URL=loopback_models,
        FIXTURE_SLOW_MATRIX_WRITE="3",
    )
    tail = StderrTail(proc)
    stdio_initialize(proc)
    tail.wait_for("matrix write begun")
    if how == "signal":
        proc.send_signal(signal.SIGTERM)
    else:
        proc.stdin.close()
    stderr = clean_exit(proc, tail, 5.0)
    assert "http client closed" in stderr and "engine disposed" in stderr
    assert_matrix_whole(tmp_path)


def test_the_task_is_cancelled_before_the_client_closes_in_a_real_stdio_process(
    tmp_path, loopback_models
):
    """The fixture's real aclose() notes that it ran; the task's cancel is logged first."""
    proc = start_fixture_server(
        tmp_path, "stdio", PERPLEXITY_BASE_URL=loopback_models, FIXTURE_SLOW_MATRIX_WRITE="3"
    )
    tail = StderrTail(proc)
    stdio_initialize(proc)
    tail.wait_for("matrix write begun")
    proc.send_signal(signal.SIGINT)
    stderr = clean_exit(proc, tail, 5.0)
    assert stderr.index("model matrix refresh stopped") < stderr.index("http client closed")


class _ModelsAndAgent(BaseHTTPRequestHandler):
    """The models endpoint with one model the baseline does not know, and an agent endpoint that
    completes every request: enough for a real process to lease, probe and finish that model."""

    models = json.dumps(payload_with("acme/new-1")).encode()
    count = 0

    def _reply(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply(self.models)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        type(self).count += 1
        body = fixture("agent_fast.json")
        body["id"] = f"resp_signal-{type(self).count}"
        self._reply(json.dumps(body).encode())

    def log_message(self, *_args):
        pass


def test_stdio_signal_during_the_shielded_finish_write_lets_the_finish_land(tmp_path):
    """The three writes of a probe round, in order: the merge, the lease, the finish. The signal
    arrives while the third is in flight (the fixture's slow write logs when each begins); the
    shield must let it complete, so the model is stored as probed and the file is whole."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelsAndAgent)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        proc = start_fixture_server(
            tmp_path,
            "stdio",
            PERPLEXITY_BASE_URL=f"http://127.0.0.1:{server.server_address[1]}",
            FIXTURE_SLOW_MATRIX_WRITE="1.5",
        )
        tail = StderrTail(proc)
        stdio_initialize(proc)
        deadline = time.monotonic() + 20
        while sum("matrix write begun" in line for line in list(tail.lines)) < 3:
            assert time.monotonic() < deadline, "the third write never began:\n" + "".join(
                tail.lines
            )
            time.sleep(0.02)
        proc.send_signal(signal.SIGTERM)
        stderr = clean_exit(proc, tail, 8.0)
        assert "http client closed" in stderr
    finally:
        server.shutdown()
        server.server_close()
    loaded = matrix.load(tmp_path / "data" / matrix.FILENAME)
    assert loaded.state == "ok"
    row = loaded.matrix.models["acme/new-1"]
    assert row.efforts.source == "probe" and row.probing_until is None

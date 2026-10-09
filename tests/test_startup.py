"""Startup order and failure: settings, then data dir and migrations, then client, then listener."""

import logging
import sqlite3
import subprocess
import sys

import pytest
from server_support import free_port, server_env

from mcp_perplexity_pro import __main__ as entry


def run_main(tmp_path, *args, drop=(), **extra_env):
    env = server_env(tmp_path, **extra_env)
    for name in drop:
        env.pop(name, None)
    return subprocess.run(
        [sys.executable, "-m", "mcp_perplexity_pro", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_missing_key_exits_nonzero_and_creates_nothing(tmp_path):
    result = run_main(tmp_path, "--transport", "http", drop=("PERPLEXITY_API_KEY",))
    assert result.returncode != 0
    assert "PERPLEXITY_API_KEY" in result.stderr
    assert result.stdout == ""
    assert not (tmp_path / "data").exists()  # the data directory was never created
    assert list((tmp_path / "home").iterdir()) == []  # and nothing else landed in HOME


def test_invalid_setting_creates_nothing_either(tmp_path):
    result = run_main(tmp_path, "--transport", "http", PERPLEXITY_PORT="not-a-port")
    assert result.returncode != 0
    assert "PERPLEXITY_PORT" in result.stderr and "not-a-port" in result.stderr
    assert not (tmp_path / "data").exists()


def test_failing_migration_exits_nonzero_before_any_listener(tmp_path):
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    with sqlite3.connect(data / "perplexity.db") as conn:  # a revision this code does not know
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version VALUES ('from_the_future')")
    port = free_port()
    result = run_main(tmp_path, "--transport", "http", PERPLEXITY_PORT=str(port))
    assert result.returncode != 0
    assert "from_the_future" in result.stderr
    assert "Application startup complete" not in result.stderr  # uvicorn never started
    # The process is gone and nothing ever listened, so /health cannot have been served.
    import socket

    with pytest.raises(ConnectionRefusedError), socket.create_connection(("127.0.0.1", port), 1):
        pass


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    fastmcp = logging.getLogger("fastmcp")
    saved = (list(root.handlers), root.level, list(fastmcp.handlers), fastmcp.propagate)
    yield
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    fastmcp.handlers[:] = saved[2]
    fastmcp.propagate = saved[3]


async def test_startup_steps_run_in_the_required_order(make_settings, monkeypatch, restore_logging):
    import httpx2

    from mcp_perplexity_pro import server as server_module
    from mcp_perplexity_pro import settings as settings_module
    from mcp_perplexity_pro.storage import engine as engine_module
    from mcp_perplexity_pro.storage import migrate as migrate_module

    steps = []
    settings = make_settings()

    def spy(name, real):
        def wrapper(*args, **kwargs):
            steps.append(name)
            return real(*args, **kwargs)

        return wrapper

    class SpyClient(httpx2.AsyncClient):
        def __init__(self, *args, **kwargs):
            steps.append("client")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(settings_module, "load_settings", spy("settings", lambda: settings))
    monkeypatch.setattr(migrate_module, "migrate", spy("migrate", migrate_module.migrate))
    monkeypatch.setattr(
        engine_module, "create_engine_for", spy("engine", engine_module.create_engine_for)
    )
    monkeypatch.setattr(httpx2, "AsyncClient", SpyClient)
    monkeypatch.setattr(server_module, "build_server", spy("server", server_module.build_server))
    server, _ = entry.bootstrap()
    assert steps == ["settings", "migrate", "engine", "client", "server"]
    assert (settings.data_dir / "perplexity.db").exists()
    await server.app.http.aclose()
    await server.app.engine.dispose()

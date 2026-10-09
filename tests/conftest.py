"""Shared fixtures: an offline-by-default network guard and a dummy API key."""

import ipaddress
import socket

import pytest
from chat_support import chat_world  # noqa: F401 - registers the fixture for the chat tests
from research_support import research_world  # noqa: F401 - the research and jobs tests


def _is_local(address: object) -> bool:
    """True for AF_UNIX paths and loopback IP addresses."""
    if not isinstance(address, tuple):
        return True  # AF_UNIX path or other non-IP address
    host = address[0]
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False  # a hostname other than localhost would need DNS


@pytest.fixture(autouse=True)
def _block_external_sockets(request, monkeypatch):
    """Fail any attempt to connect to a non-loopback address.

    Tests that genuinely need the network opt out with ``@pytest.mark.allow_network``.
    """
    if request.node.get_closest_marker("allow_network"):
        return

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _check(address: object) -> None:
        if not _is_local(address):
            raise RuntimeError(f"network access blocked in tests: {address!r}")

    def guarded_connect(self, address):
        _check(address)
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        _check(address)
        return real_connect_ex(self, address)

    guarded_connect._network_guard = True
    guarded_connect_ex._network_guard = True
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


@pytest.fixture
def dummy_api_key() -> str:
    """A key-shaped value that is deliberately not key-shaped to the secret scanners."""
    return "test-dummy-api-key"


@pytest.fixture
def make_settings(dummy_api_key, monkeypatch, tmp_path):
    """Build ``Settings`` without reading the real environment or home directory."""
    from mcp_perplexity_pro.settings import Settings

    for name in list(__import__("os").environ):
        if name.startswith("PERPLEXITY_"):
            monkeypatch.delenv(name)

    def factory(**overrides):
        values = {"api_key": dummy_api_key, "data_dir": tmp_path / "data"}
        values.update(overrides)
        return Settings(**values)

    return factory


@pytest.fixture
async def storage_engine(make_settings):
    """A migrated async engine on a temp-file database, plus a TEST-ONLY child table.

    ``notes`` references ``projects`` with ON DELETE CASCADE; it exists only in tests, standing
    in for the project-scoped tables later changes add.
    """
    from sqlalchemy import text

    from mcp_perplexity_pro.storage.engine import create_engine_for
    from mcp_perplexity_pro.storage.migrate import migrate

    settings = make_settings()
    migrate(settings)
    engine = create_engine_for(settings)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT NOT NULL, "
                "project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE)"
            )
        )
    yield engine
    await engine.dispose()

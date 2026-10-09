"""Smoke tests for the scaffold and the offline-by-default guarantees."""

import socket

import pytest

import mcp_perplexity_pro


def test_package_imports():
    assert mcp_perplexity_pro.__doc__


def test_live_marker_is_deselected_by_default(request):
    assert request.config.getini("addopts") == ["-m", "not live and not build"]


def test_dummy_api_key_fixture(dummy_api_key):
    assert dummy_api_key.startswith("test-")
    assert not dummy_api_key.startswith("pplx-")


def test_public_address_is_blocked():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="blocked"):
            sock.connect(("93.184.216.34", 80))
    finally:
        sock.close()


def test_loopback_is_not_blocked_by_the_guard():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError) as excinfo:
            sock.connect(("127.0.0.1", 1))  # nothing listens on port 1
        assert "blocked" not in str(excinfo.value)
    finally:
        sock.close()


def test_guard_is_installed_by_default():
    assert getattr(socket.socket.connect, "_network_guard", False)


@pytest.mark.allow_network
def test_opt_out_marker_removes_guard():
    assert not getattr(socket.socket.connect, "_network_guard", False)

"""Subprocess helper (not a test): the real startup and ``run()`` plus test-only tools.

Usage: ``python tests/fixture_server.py stdio|http``. Configuration comes from ``PERPLEXITY_*``
environment variables, exactly as in production; only the two tools below are added.
"""

import asyncio
import logging
import os
import sys

from mcp_perplexity_pro.__main__ import bootstrap, run

server, settings = bootstrap()
log = logging.getLogger("fixture_tool")


def _note(path, label):
    with open(path, "a") as handle:
        handle.write(label + "\n")


def _record_real_closure(path):
    """Append a line to ``path`` once a close really ran. The log line alone is no proof: it
    would survive a deleted close call. AsyncEngine is slotted, so the sync engine under it is
    wrapped (``AsyncEngine.dispose`` delegates to it)."""
    http = server.app.http
    original_aclose = http.aclose

    async def aclose():
        await original_aclose()
        _note(path, "http.aclose")

    http.aclose = aclose
    sync_engine = server.app.engine.sync_engine
    original_dispose = sync_engine.dispose

    def dispose(*args, **kwargs):
        original_dispose(*args, **kwargs)
        _note(path, "engine.dispose")

    sync_engine.dispose = dispose


if os.environ.get("FIXTURE_CLOSE_LOG"):
    _record_real_closure(os.environ["FIXTURE_CLOSE_LOG"])


@server.tool
async def log_all() -> str:
    """Log once at every level."""
    log.debug("fixture-debug-line")
    log.info("fixture-info-line")
    log.warning("fixture-warning-line")
    log.error("fixture-error-line")
    log.critical("fixture-critical-line")
    return "logged"


@server.tool
async def nap(seconds: float) -> str:
    """Sleep, then answer; stands in for a long-running call."""
    log.info("nap started")
    await asyncio.sleep(seconds)
    return "rested"


if __name__ == "__main__":
    timeout = os.environ.get("FIXTURE_GRACEFUL_TIMEOUT")
    extra = {"graceful_timeout": float(timeout)} if timeout else {}
    run(server, settings, transport=sys.argv[1], **extra)

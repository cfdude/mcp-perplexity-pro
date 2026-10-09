"""Subprocess helper (not a test): the real startup and ``run()`` plus test-only tools.

Usage: ``python tests/fixture_server.py stdio|http``. Configuration comes from ``PERPLEXITY_*``
environment variables, exactly as in production; only the two tools below are added.
"""

import asyncio
import logging
import sys

from mcp_perplexity_pro.__main__ import bootstrap, run

server, settings = bootstrap()
log = logging.getLogger("fixture_tool")


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
    run(server, settings, transport=sys.argv[1])

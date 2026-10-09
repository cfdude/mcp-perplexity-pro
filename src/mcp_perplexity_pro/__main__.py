"""Entry point: ``mcp-perplexity-pro [--transport stdio|http]`` (also ``python -m``).

``main()`` performs startup in the order the server-runtime spec requires and then hands the
built server to ``run()``, which a test module can call with its own server.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import TYPE_CHECKING

from mcp_perplexity_pro.cli import parse_args

if TYPE_CHECKING:
    import uvicorn
    from fastmcp import FastMCP

    from mcp_perplexity_pro.settings import Settings

logger = logging.getLogger("mcp_perplexity_pro")

HTTP_PATH = "/mcp"
GRACEFUL_TIMEOUT = 10  # seconds in-flight requests may take after a stop signal


def _fail(message: str) -> SystemExit:
    print(message, file=sys.stderr, flush=True)
    return SystemExit(1)


def bootstrap() -> tuple[FastMCP, Settings]:
    """Startup in the required order; returns the built server, ready for ``run()``.

    Any failure exits non-zero before a listener exists.
    """
    # FastMCP checks PyPI and writes a cache file under the user's home when its banner shows;
    # the banner is never shown, and this is the second guard. Set before fastmcp is imported.
    os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")

    import httpx2

    from mcp_perplexity_pro.log_setup import configure_logging
    from mcp_perplexity_pro.server import build_server
    from mcp_perplexity_pro.settings import SettingsError, load_settings
    from mcp_perplexity_pro.storage.engine import StorageError, create_engine_for
    from mcp_perplexity_pro.storage.migrate import migrate

    # 1. Settings: side-effect free, so a failure here leaves nothing on disk.
    try:
        settings = load_settings()
    except SettingsError as exc:
        raise _fail(str(exc)) from None
    configure_logging(settings.log_level, [settings.api_key.get_secret_value()])

    # 2. Data directory and migrations. A failure aborts before anything listens.
    try:
        migrate(settings)
        engine = create_engine_for(settings)
    except StorageError as exc:
        logger.error("startup failed: %s", exc)
        raise SystemExit(1) from None

    # 3. Upstream client; the listener opens later, inside run().
    return build_server(settings, httpx2.AsyncClient(), engine), settings


def main(argv: list[str] | None = None) -> None:
    """Parse arguments, run the startup sequence, then serve."""
    args = parse_args(argv)
    server, settings = bootstrap()
    run(server, settings, transport=args.transport)


def build_http_server(server: FastMCP, settings: Settings) -> uvicorn.Server:
    """A ``uvicorn.Server`` for ``server`` on ``settings.host:settings.port``; nothing is bound."""
    import uvicorn

    class _Server(uvicorn.Server):
        # uvicorn's own handle_exit also records the signal in ``_captured_signals``, which
        # ``capture_signals()`` re-raises once shutdown completes, so the process would die by
        # signal (exit 143). Not recording it is what makes the exit status 0.
        def handle_exit(self, sig: int, frame: object) -> None:
            if self.should_exit and sig == signal.SIGINT:
                self.force_exit = True
            else:
                self.should_exit = True

    app = server.http_app(
        path=HTTP_PATH, stateless_http=True, json_response=True, host_origin_protection=True
    )
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        lifespan="on",
        timeout_graceful_shutdown=GRACEFUL_TIMEOUT,
        log_config=None,  # our redacting stderr handler is the only logging configuration
        log_level=settings.log_level.lower(),
    )
    return _Server(config)


async def close_resources(server: FastMCP) -> None:
    """Close the caller-owned HTTP client and database engine, logging each closure."""
    app = server.app  # type: ignore[attr-defined]
    try:
        await app.http.aclose()
        logger.info("http client closed")
    finally:
        await app.engine.dispose()
        logger.info("engine disposed")


def run(server: FastMCP, settings: Settings, transport: str = "stdio") -> None:
    """Serve ``server`` until stopped, then close its resources."""
    if transport == "http":
        asyncio.run(_run_http(server, settings))
    else:
        asyncio.run(_run_stdio(server))


async def _run_http(server: FastMCP, settings: Settings) -> None:
    try:
        await build_http_server(server, settings).serve()
    finally:
        await close_resources(server)


async def _run_stdio(server: FastMCP) -> None:
    try:
        await server.run_stdio_async(show_banner=False)
    finally:
        await close_resources(server)


if __name__ == "__main__":
    main()

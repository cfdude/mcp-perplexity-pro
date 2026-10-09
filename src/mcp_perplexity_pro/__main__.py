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
STDOUT_FLUSH_GRACE = 0.3  # seconds for a finished call's reply to reach stdout before exit


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


def build_http_server(
    server: FastMCP, settings: Settings, graceful_timeout: float = GRACEFUL_TIMEOUT
) -> uvicorn.Server:
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

    # json_response=True: with SSE responses uvicorn aborts in-flight calls the moment it
    # starts shutting down; plain JSON responses are drained for ``graceful_timeout`` seconds.
    app = server.http_app(
        path=HTTP_PATH, stateless_http=True, json_response=True, host_origin_protection=True
    )
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        lifespan="on",
        timeout_graceful_shutdown=graceful_timeout,
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


def run(
    server: FastMCP,
    settings: Settings,
    transport: str = "stdio",
    *,
    graceful_timeout: float = GRACEFUL_TIMEOUT,
) -> None:
    """Serve ``server`` until stopped, then close its resources and return (exit status 0).

    ``graceful_timeout`` is how long in-flight calls may run after a stop signal; production
    uses the 10 s default, tests pass less so a cut-off scenario does not take 10 s.
    """
    if transport == "http":
        asyncio.run(_run_http(server, settings, graceful_timeout))
    else:
        asyncio.run(_run_stdio(server, graceful_timeout))


async def _run_http(server: FastMCP, settings: Settings, graceful_timeout: float) -> None:
    # uvicorn stops accepting at SIGTERM/SIGINT, drains in-flight requests for
    # ``graceful_timeout`` and cancels what is left; its lifespan shutdown runs after that.
    try:
        await build_http_server(server, settings, graceful_timeout).serve()
    finally:
        await close_resources(server)


async def _drain_and_close(server: FastMCP, graceful_timeout: float) -> None:
    """Stop taking tool calls, wait for running ones (bounded), then close resources."""
    in_flight = server.in_flight  # type: ignore[attr-defined]
    in_flight.start_draining()
    had_calls = in_flight.count > 0
    if had_calls:
        logger.info("shutdown: waiting up to %gs for %d call(s)", graceful_timeout, in_flight.count)
    if not await in_flight.wait_idle(graceful_timeout):
        logger.warning("shutdown: %d call(s) still running; cutting them off", in_flight.count)
    elif had_calls:
        # The result is written to stdout by another task just after the tool returns; give it
        # a moment so a hard exit cannot drop the answer the client was promised.
        await asyncio.sleep(STDOUT_FLUSH_GRACE)
    await close_resources(server)


async def _run_stdio(server: FastMCP, graceful_timeout: float) -> None:
    """stdio: leaves on stdin EOF, SIGTERM or SIGINT, always with exit status 0.

    ``mcp.run()`` hangs on SIGINT in stdio mode (a thread blocked reading stdin) and dies by
    signal on SIGTERM, so signals are handled here and end in ``os._exit(0)`` after cleanup.
    """
    loop = asyncio.get_running_loop()
    stopping: list[asyncio.Task[None]] = []  # holds the task so it is not garbage collected

    async def stop_on_signal() -> None:
        await _drain_and_close(server, graceful_timeout)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)  # a blocked stdin reader thread would otherwise hang the exit

    def on_signal() -> None:
        if not stopping:
            stopping.append(loop.create_task(stop_on_signal()))

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, on_signal)
    try:
        await server.run_stdio_async(show_banner=False)  # returns on stdin EOF
    finally:
        if not stopping:  # EOF path (a signal's task already owns the cleanup)
            await _drain_and_close(server, graceful_timeout)
        else:
            await asyncio.shield(stopping[0])


if __name__ == "__main__":
    main()

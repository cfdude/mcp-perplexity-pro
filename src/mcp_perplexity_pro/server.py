"""The FastMCP server: dependencies and ``/health``.

``build_server(settings, http, engine)`` wires injected dependencies (design D2). The caller owns
``http`` and ``engine`` and closes them (``__main__.run`` does); the lifespan only exposes them.

Tools reach the dependencies through ``ctx.lifespan_context`` (an ``AppContext``) and open a
database session with ``storage.session.unit_of_work(app.engine)``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from importlib.metadata import version as package_version
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from fastmcp.exceptions import NotFoundError, ValidationError
from fastmcp.server.lifespan import lifespan
from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from mcp_perplexity_pro.agent import JobLocks
from mcp_perplexity_pro.catalog import Catalog
from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import ALL_CATEGORIES, PerplexityError
from mcp_perplexity_pro.redaction import redact_text
from mcp_perplexity_pro.storage.session import is_busy_error, storage_busy_error
from mcp_perplexity_pro.tools import register_tools
from mcp_perplexity_pro.usage import failure_summary, utcnow

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    import httpx2
    from sqlalchemy.ext.asyncio import AsyncEngine
    from starlette.requests import Request

    from mcp_perplexity_pro.settings import Settings

PACKAGE_NAME = "mcp-perplexity-pro"
GENERIC_MESSAGE = "An internal error occurred while running the tool."
DRAINING_MESSAGE = "The server is shutting down and is not accepting new tool calls."

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppContext:
    """What tools get from ``ctx.lifespan_context``; every member is owned by the caller."""

    settings: Settings
    http: httpx2.AsyncClient
    client: PerplexityClient
    engine: AsyncEngine
    catalog: Catalog
    # OUR clock for research jobs (naive UTC); tests inject one
    now: Callable[[], datetime] = utcnow
    # one in-process lock per research job (design D8)
    job_locks: JobLocks = field(default_factory=JobLocks)


def error_result(category: str, message: str) -> ToolResult:
    """The one wire shape of a tool failure.

    ``structuredContent`` and ``_meta`` carry the machine-readable ``category``; the text
    content repeats it as a ``[category]`` prefix for a client that shows only text.
    ``category`` must be one of the closed vocabulary (``errors.ALL_CATEGORIES``).
    """
    if category not in ALL_CATEGORIES:
        raise ValueError(f"unknown error category {category!r}")
    return ToolResult(
        content=f"[{category}] {message}",
        structured_content={"category": category, "message": message},
        meta={"category": category},
        is_error=True,
    )


class InFlightMiddleware(Middleware):
    """Counts running tool calls; once draining, refuses new ones."""

    def __init__(self) -> None:
        self.count = 0
        self.draining = False
        self._idle = asyncio.Event()
        self._idle.set()

    def start_draining(self) -> None:
        self.draining = True

    async def wait_idle(self, timeout: float) -> bool:
        """Wait until no call is running; False if ``timeout`` seconds elapsed first."""
        try:
            await asyncio.wait_for(self._idle.wait(), timeout)
        except TimeoutError:
            return False
        return True

    async def on_call_tool(self, context: Any, call_next: Any) -> Any:
        if self.draining:
            return error_result("internal_error", DRAINING_MESSAGE)
        self.count += 1
        self._idle.clear()
        try:
            return await call_next(context)
        finally:
            self.count -= 1
            if self.count == 0:
                self._idle.set()


class ErrorContractMiddleware(Middleware):
    """Turn every tool failure into ``error_result`` with a category from the closed set.

    With ``mask_error_details=True`` FastMCP wraps an unexpected exception in a generic
    ``ToolError`` (original in ``__cause__``) before middleware runs; ``PerplexityError`` is a
    ``ToolError`` and passes through unmasked.
    """

    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        self._secrets = secrets

    async def on_call_tool(self, context: Any, call_next: Any) -> Any:
        try:
            return await call_next(context)
        except PerplexityError as exc:
            # PerplexityError already redacts what it was built with; this covers a message
            # that gained text afterwards, or a subclass that skipped its own redaction.
            return error_result(exc.category, redact_text(str(exc), self._secrets))
        except Exception as exc:
            return self._classify(context, exc)

    def _classify(self, context: Any, exc: Exception) -> ToolResult:
        root = exc.__cause__ or exc
        if is_busy_error(exc) or is_busy_error(root):
            busy = storage_busy_error()
            return error_result(busy.category, str(busy))
        if isinstance(exc, ValidationError):  # FastMCP's: arguments failed schema validation
            return error_result("invalid_request", redact_text(str(exc), self._secrets))
        if isinstance(exc, NotFoundError):
            return error_result("not_found", redact_text(str(exc), self._secrets))
        name = getattr(getattr(context, "message", None), "name", "?")
        if isinstance(root, SQLAlchemyError):
            # its traceback text renders [parameters: ...], every bound value (stored answers,
            # chat text): only the type and the driver's own message are logged
            logger.error(
                "tool %r failed unexpectedly: %s", name, failure_summary(root, self._secrets)
            )
        else:
            # exc_info carries the full detail; the logging filter redacts it before it is written.
            logger.error("tool %r failed unexpectedly", name, exc_info=root)
        return error_result("internal_error", GENERIC_MESSAGE)


def build_server(
    settings: Settings,
    http: httpx2.AsyncClient,
    engine: AsyncEngine,
    *,
    clock: Callable[[], float] = time.time,
    now: Callable[[], datetime] = utcnow,
) -> FastMCP:
    """Build the server around caller-owned ``http`` and ``engine``.

    ``clock`` (wall-clock seconds) drives the model-catalog cache and ``now`` (a naive UTC
    datetime) the research jobs' own times; tests inject fake ones.

    ``server.app`` is the ``AppContext`` (so ``__main__.run`` can close its members) and
    ``server.in_flight`` the ``InFlightMiddleware`` (so stdio shutdown can wait for calls).
    """
    pkg_version = package_version(PACKAGE_NAME)
    client = PerplexityClient(settings, http=http)
    app = AppContext(
        settings=settings,
        http=http,
        client=client,
        engine=engine,
        catalog=Catalog(
            client,
            ttl=settings.catalog_ttl,
            max_stale=settings.catalog_max_stale,
            clock=clock,
        ),
        now=now,
    )

    @lifespan
    async def app_lifespan(_server: FastMCP):
        yield app  # the caller closes these; a signal never reaches this teardown in stdio mode

    in_flight = InFlightMiddleware()
    server = FastMCP(
        "perplexity-pro",
        version=pkg_version,
        lifespan=app_lifespan,
        mask_error_details=True,
        middleware=[in_flight, ErrorContractMiddleware((settings.api_key.get_secret_value(),))],
    )

    @server.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": pkg_version})

    register_tools(server)  # tools exist from construction, so the tool contract covers them

    server.app = app  # type: ignore[attr-defined]
    server.in_flight = in_flight  # type: ignore[attr-defined]
    return server

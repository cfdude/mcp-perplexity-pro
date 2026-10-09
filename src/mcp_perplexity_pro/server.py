"""The FastMCP server: dependencies and ``/health``.

``build_server(settings, http, engine)`` wires injected dependencies (design D2). The caller owns
``http`` and ``engine`` and closes them (``__main__.run`` does); the lifespan only exposes them.

Tools reach the dependencies through ``ctx.lifespan_context`` (an ``AppContext``) and open a
database session with ``storage.session.unit_of_work(app.engine)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version as package_version
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan
from starlette.responses import JSONResponse

from mcp_perplexity_pro.client import PerplexityClient

if TYPE_CHECKING:
    import httpx2
    from sqlalchemy.ext.asyncio import AsyncEngine
    from starlette.requests import Request

    from mcp_perplexity_pro.settings import Settings

PACKAGE_NAME = "mcp-perplexity-pro"


@dataclass(frozen=True)
class AppContext:
    """What tools get from ``ctx.lifespan_context``; every member is owned by the caller."""

    settings: Settings
    http: httpx2.AsyncClient
    client: PerplexityClient
    engine: AsyncEngine


def build_server(settings: Settings, http: httpx2.AsyncClient, engine: AsyncEngine) -> FastMCP:
    """Build the server around caller-owned ``http`` and ``engine``.

    ``server.app`` is the ``AppContext`` (so ``__main__.run`` can close its members).
    """
    pkg_version = package_version(PACKAGE_NAME)
    app = AppContext(
        settings=settings,
        http=http,
        client=PerplexityClient(settings, http=http),
        engine=engine,
    )

    @lifespan
    async def app_lifespan(_server: FastMCP):
        yield app  # the caller closes these; a signal never reaches this teardown in stdio mode

    server = FastMCP(
        "perplexity-pro",
        version=pkg_version,
        lifespan=app_lifespan,
        mask_error_details=True,
    )

    @server.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": pkg_version})

    server.app = app  # type: ignore[attr-defined]
    return server

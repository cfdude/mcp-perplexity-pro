"""One module per tool, each exposing ``register(server)``; ``register_tools`` calls them all.

Tools reach the client, catalog and engine through ``ctx.lifespan_context`` (an
``AppContext``), open database sessions with ``storage.session.unit_of_work`` and raise
``PerplexityError(category, message)`` for every anticipated failure. Do not use
``from __future__ import annotations`` in a tool module: FastMCP reads the parameter
annotations at registration time (``Context`` must be a real class there).
"""

from fastmcp import FastMCP

from mcp_perplexity_pro.tools import models, projects


def register_tools(server: FastMCP) -> None:
    models.register(server)
    projects.register(server)

"""Helpers for the Agent tool tests: a server built through ``build_server`` over a
request-capturing ``MockTransport`` that serves recorded fixtures (the pattern of
``tests/test_usage_e2e.py``), plus small readers for the database and the requests."""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx2
from fastmcp import Client
from fixture_support import FIXTURE_DIR
from sqlalchemy import text
from usage_support import Upstream

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate


def fixture(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text())


def respond_with(name: str, status: int = 200):
    """A responder serving a fixture body (a fresh copy per call)."""
    return lambda request, n: httpx2.Response(status, json=fixture(name))


def respond_body(body: Any, status: int = 200):
    return lambda request, n: httpx2.Response(status, json=body)


def inline(status: str, **extra: Any) -> dict[str, Any]:
    """A synthetic Agent response body (edge cases are built inline, never as fixtures)."""
    return {"id": "resp_inline-1", "status": status, "output": [], **extra}


@dataclass
class World:
    server: Any
    engine: Any
    upstream: Upstream
    http: Any
    settings: Any
    requests: list = field(default_factory=list)

    def bodies(self) -> list[dict[str, Any]]:
        """The JSON bodies of the POSTs the upstream received, in order."""
        return [json.loads(r.content) for r in self.requests if r.content]

    async def call(self, tool: str, **arguments: Any):
        async with Client(self.server) as client:
            return await client.call_tool(tool, arguments, raise_on_error=False)

    async def count(self, table: str) -> int:
        async with self.engine.connect() as conn:
            return (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()

    async def rows(self, sql: str, **params: Any) -> list[tuple]:
        async with self.engine.connect() as conn:
            return [tuple(r) for r in await conn.execute(text(sql), params)]

    async def events(self) -> list[tuple]:
        return await self.rows(
            "SELECT tool, api, status, preset, model, request_id, project_name, "
            "cost_nano_usd, cost_source FROM usage_events ORDER BY id"
        )

    async def aclose(self) -> None:
        await self.http.aclose()
        await self.engine.dispose()


async def make_world(make_settings, responder, *, now=None, **settings: Any) -> World:
    cfg = make_settings(**{"max_attempts": 1, **settings})
    migrate(cfg)
    engine = create_engine_for(cfg)
    requests: list = []
    upstream = Upstream(responder)

    async def handler(request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        requests.append(request)
        return await upstream(request)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    server = build_server(cfg, http, engine, **({} if now is None else {"now": now}))
    return World(server, engine, upstream, http, cfg, requests)

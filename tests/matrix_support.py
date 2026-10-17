"""Helpers for the model-matrix refresh and probe tests: a path-aware upstream and a world
built through ``build_server`` over a ``MockTransport`` (no network, the real server code)."""

import asyncio
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx2
from fixture_support import FIXTURE_DIR
from sqlalchemy import text

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate


def models_payload() -> dict[str, Any]:
    """The recorded live list of 2026-10-17 (54 models), a fresh copy per call."""
    return json.loads((FIXTURE_DIR / "models_2026-10-17.json").read_text())


def payload_with(*ids: str, price: float = 1.0) -> dict[str, Any]:
    """The recorded live list plus extra models the baseline does not know."""
    payload = models_payload()
    for model_id in ids:
        payload["data"].append(
            {
                "id": model_id,
                "object": "model",
                "created": 0,
                "owned_by": model_id.split("/")[0],
                "pricing": {"input": price, "output": price, "unit": "usd_per_1m_tokens"},
            }
        )
    return payload


class Upstream:
    """A path-aware fake of the API. ``models`` is the body of ``GET /v1/models`` (or a status
    to answer with); ``gate`` holds that endpoint open until it is set; ``agent`` is a responder
    ``(request_body, n) -> httpx2.Response`` for ``POST /v1/agent``."""

    def __init__(
        self,
        *,
        models: dict[str, Any] | None = None,
        models_status: int = 200,
        gate: asyncio.Event | None = None,
        agent: Callable[[dict[str, Any], int], Any] | None = None,
    ) -> None:
        self.models = models if models is not None else models_payload()
        self.models_status = models_status
        self.gate = gate
        self.agent = agent
        self.requests: list[httpx2.Request] = []
        self.agent_bodies: list[dict[str, Any]] = []

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def count(self, path: str) -> int:
        return self.paths().count(path)

    async def handler(self, request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        self.requests.append(request)
        if request.url.path == "/v1/models":
            if self.gate is not None:
                await self.gate.wait()
            if self.models_status != 200:
                return httpx2.Response(
                    self.models_status, json={"error": {"message": "models are down"}}
                )
            return httpx2.Response(200, json=self.models)
        if request.url.path == "/v1/agent" and self.agent is not None:
            body = json.loads(request.content)
            self.agent_bodies.append(body)
            reply = self.agent(body, len(self.agent_bodies))
            return await reply if inspect.isawaitable(reply) else reply
        return httpx2.Response(500, json={"error": {"message": f"unexpected {request.url.path}"}})


@dataclass
class MatrixWorld:
    server: Any
    engine: Any
    http: Any
    settings: Any
    upstream: Upstream
    closed: list[str] = field(default_factory=list)

    @property
    def app(self):
        return self.server.app

    async def rows(self, sql: str, **params: Any) -> list[tuple]:
        async with self.engine.connect() as conn:
            return [tuple(r) for r in await conn.execute(text(sql), params)]

    async def aclose(self) -> None:
        await self.http.aclose()
        await self.engine.dispose()


async def make_matrix_world(
    make_settings, upstream: Upstream, *, refresh_task: bool = True, **settings: Any
) -> MatrixWorld:
    cfg = make_settings(**{"max_attempts": 1, **settings})
    migrate(cfg)
    engine = create_engine_for(cfg)
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream.handler))
    server = build_server(cfg, http, engine, matrix_refresh=refresh_task)
    return MatrixWorld(server, engine, http, cfg, upstream)

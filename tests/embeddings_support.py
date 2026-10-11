"""Helpers for the embeddings tests: a recorded-vector responder, a world with a real engine and a
``MockTransport``, and small seeders for chats, jobs and projects."""

import base64
import json
from datetime import datetime
from types import SimpleNamespace

import httpx2
from fixture_support import FIXTURE_DIR
from sqlalchemy import text
from usage_support import Upstream

from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.embeddings import FULL_DIMENSIONS, ProjectLocks
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate
from mcp_perplexity_pro.storage.models import Chat, ChatMessage, Project, ResearchJob
from mcp_perplexity_pro.storage.session import unit_of_work

NOW = datetime(2026, 10, 11, 12, 0, 0)
M6 = "pplx-embed-v1-0.6b"
M4 = "pplx-embed-v1-4b"


def fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


# 64 REAL 128-dimension int8 vectors (embeddings_64_inputs_4000_chars), reused by cycling
REAL = [
    base64.b64decode(d["embedding"])
    for d in fixture("embeddings_64_inputs_4000_chars.json")["data"]
]
NANO_PER_INPUT = 40  # the synthetic usage below: 10 tokens per input at 4 nano-USD per token


def vector_for(position: int, dimensions: int, encoding: str) -> bytes:
    if encoding == "binary":
        return bytes((position * 7 + i) % 256 for i in range(dimensions // 8))
    base = REAL[position % len(REAL)]
    return (base * (dimensions // len(base) + 1))[:dimensions]


def embed_response(request: httpx2.Request, *, wrong_length=False, short_data=False, model=M6):
    """A response sized to the request's inputs: real vectors, 10 tokens and 40 nano-USD each."""
    body = json.loads(request.content)
    inputs = body["input"]
    encoding = "binary" if body["encoding_format"] == "base64_binary" else "int8"
    dimensions = body.get("dimensions") or FULL_DIMENSIONS[body["model"]]
    data = []
    for i in range(len(inputs)):
        vector = vector_for(i, dimensions, encoding)
        if wrong_length and i == 0:
            vector = vector[:-1]
        data.append(
            {"object": "embedding", "index": i, "embedding": base64.b64encode(vector).decode()}
        )
    if short_data:
        data = data[:-1]
    n = len(inputs)
    usage = {
        "prompt_tokens": 10 * n,
        "total_tokens": 10 * n,
        "cost": {"currency": "USD", "input_cost": 4e-8 * n, "total_cost": 4e-8 * n},
    }
    return httpx2.Response(
        200, json={"object": "list", "data": data, "model": body["model"], "usage": usage}
    )


async def make_app(make_settings, responder, **settings):
    cfg = make_settings(max_attempts=1, **settings)
    migrate(cfg)
    engine = create_engine_for(cfg)
    upstream = Upstream(responder)
    requests: list[httpx2.Request] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        requests.append(request)
        return await upstream(request)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    client = PerplexityClient(cfg, http=http)
    app = SimpleNamespace(settings=cfg, client=client, engine=engine, embed_locks=ProjectLocks())
    app.upstream = upstream
    app.upstream_requests = requests
    app.http = http
    return app


async def close_app(app):
    await app.http.aclose()
    await app.engine.dispose()


async def add_project(app, name="p"):
    async with unit_of_work(app.engine) as session:
        proj = Project(name=name)
        session.add(proj)
        await session.flush()
        return proj.id


async def add_chat(app, pid, *contents):
    async with unit_of_work(app.engine) as session:
        chat = Chat(project_id=pid, title="t", created_at=NOW, updated_at=NOW)
        session.add(chat)
        await session.flush()
        ids = []
        for i, content in enumerate(contents):
            message = ChatMessage(
                chat_id=chat.id,
                role="user" if i % 2 == 0 else "assistant",
                content=content,
                created_at=NOW,
            )
            session.add(message)
            await session.flush()
            ids.append(message.id)
        return chat.id, ids


_serial = iter(range(1, 100_000))


async def add_job(app, pid, status="completed", result="a research report"):
    async with unit_of_work(app.engine) as session:
        job = ResearchJob(
            project_id=pid,
            query="q",
            depth="medium",
            response_id=f"resp_{next(_serial)}",
            status=status,
            started_at=NOW,
            result_text=result,
        )
        session.add(job)
        await session.flush()
        return job.id


async def rows(app, sql, **params):
    async with app.engine.connect() as conn:
        return [tuple(r) for r in await conn.execute(text(sql), params)]


async def events(app):
    return await rows(
        app,
        "SELECT tool, api, status, model, request_id, project_name, input_tokens, total_tokens, "
        "cost_nano_usd, cost_source FROM usage_events ORDER BY id",
    )


async def chunks(app):
    return await rows(
        app,
        "SELECT source, ref, chunk_index, text, model, dimensions, encoding, vector "
        "FROM embedding_chunks ORDER BY id",
    )


def fixed_response(request: httpx2.Request, vector: bytes, *, tokens=3, total_cost=1.2e-8):
    """A response whose single vector is exactly ``vector`` (the scripted query embedding)."""
    body = json.loads(request.content)
    return httpx2.Response(
        200,
        json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": 0, "embedding": base64.b64encode(vector).decode()}
            ],
            "model": body["model"],
            "usage": {
                "prompt_tokens": tokens,
                "total_tokens": tokens,
                "cost": {"currency": "USD", "input_cost": total_cost, "total_cost": total_cost},
            },
        },
    )

"""Task 8.1 (py-embeddings): every embeddings request is recorded once through
``costed.costed_call``, in the recorder's order, against a real engine and a ``MockTransport``."""

import asyncio
import json
import logging

import httpx2
import pytest
from embeddings_support import (
    M4,
    M6,
    chunks,
    close_app,
    embed_response,
    events,
    fixture,
    make_app,
    rows,
)
from usage_support import DbLock

from mcp_perplexity_pro import embeddings
from mcp_perplexity_pro.embeddings import build_request, index, run_embed
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.engine import database_path

SECRET = "zq-distinctive-embedding-text-4417"
RECORDED = "embeddings_two_4b_dim256.json"


def serve(name, status=200):
    return lambda request, n: httpx2.Response(status, json=fixture(name))


def serve_body(body, status=200, headers=None):
    return lambda request, n: httpx2.Response(status, json=body, headers=headers)


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder=None, **settings):
        app = await make_app(
            make_settings, responder or (lambda request, n: embed_response(request)), **settings
        )
        made.append(app)
        return app

    yield build
    for app in made:
        await close_app(app)


def texts(*pairs):
    return [{"key": k, "text": t} for k, t in pairs]


async def run(app, *, items=None, project="p", model=M6, **kwargs):
    return await index(
        app, project=project, source="text", items=items or texts(("a", "one")), model=model,
        dimensions=128, encoding="int8", limit=256, **kwargs,
    )  # fmt: skip


async def raw(app, project="alpha", model=M4, responder=None):
    body = build_request(model, ["a", "b"], dimensions=256)
    return await run_embed(app, project=project, body=body, model=model)


async def test_the_recorded_4b_response_is_one_reported_event_with_tokens(world):
    app = await world(serve(RECORDED))
    costed = await raw(app)
    assert costed.status == "ok" and costed.project == "alpha"  # model-matrix D7: still a name
    ((tool, api, status, model, rid, project, tin, ttot, nano, source),) = await events(app)
    assert (tool, api, status, model, rid, project) == (
        "perplexity_embed", "embeddings", "ok", M4, None, "alpha",
    )  # fmt: skip
    assert (tin, ttot, nano, source) == (12, 12, 360, "reported")
    assert await rows(app, "SELECT preset, price_table FROM usage_events") == [(None, None)]


async def test_a_response_with_no_cost_is_computed_and_with_no_usage_is_cost_zero_none(world):
    body = fixture(RECORDED)
    del body["usage"]["cost"]
    app = await world(serve_body(body))
    await raw(app)
    no_usage = fixture(RECORDED)
    del no_usage["usage"]
    app2 = await world(serve_body(no_usage))
    await raw(app2, project="beta")
    first, second = await events(app), await events(app2)
    assert (first[0][8], first[0][9]) == (360, "computed")  # 12 tokens x 30 nano (the 4b price)
    assert [(e[8], e[9]) for e in second if e[5] == "beta"] == [(0, "none")]


@pytest.mark.parametrize(
    ("responder", "category"),
    [
        (serve("embeddings_513_inputs_400.json", 400), "invalid_request"),
        (serve("embeddings_unauthenticated_401.json", 401), "authentication"),
        (serve_body({"error": {"message": "slow"}}, 429, {"Retry-After": "600"}), "rate_limited"),
        (serve_body({"error": {"message": "down"}}, 503), "upstream_failure"),
        (
            lambda request, n: (_ for _ in ()).throw(httpx2.ReadTimeout("t", request=request)),
            "network_timeout",
        ),
        (serve_body({"model": "x"}), "unexpected_response"),
    ],
    ids=["400", "401", "429", "503", "timeout", "no-data"],
)
async def test_each_failure_is_one_event_with_its_category_and_no_cost(world, responder, category):
    app = await world(responder)
    with pytest.raises(PerplexityError) as caught:
        await raw(app)
    assert caught.value.category == category
    ((*_, status, _m, _r, _p, _i, _t, nano, source),) = await events(app)
    assert (status, nano, source) == (category, 0, "none")


async def test_a_local_refusal_records_nothing_and_creates_no_project(world):
    app = await world()
    with pytest.raises(PerplexityError):
        await run(app, items=texts(("a", " ")))
    assert app.upstream.calls == 0 and await events(app) == []
    assert await rows(app, "SELECT count(*) FROM projects") == [(0,)]


async def test_a_project_created_before_a_failing_call_survives_it(world):
    app = await world(serve_body({"error": {"message": "down"}}, 503))
    with pytest.raises(PerplexityError):
        await run(app, project="beta")
    assert await rows(app, "SELECT name FROM projects") == [("beta",)]


async def test_another_connection_can_write_while_the_upstream_call_is_in_flight(world):
    app = await world()
    seen = []
    inner = app.upstream.responder

    def during(request, n):
        lock = DbLock(database_path(app.settings.data_dir))
        try:
            lock.acquire()
            seen.append("acquired")
        finally:
            lock.close()
        return inner(request, n)

    app.upstream.responder = during
    await run(app)
    assert seen == ["acquired"]


async def test_a_database_locked_past_the_busy_timeout_leaves_the_result_unchanged(
    make_settings, caplog
):
    app = await make_app(
        make_settings, lambda request, n: embed_response(request), db_busy_timeout=0.4
    )
    try:
        baseline = await run(app, items=texts(("a", "one")))
        lock = DbLock(database_path(app.settings.data_dir))
        inner = app.upstream.responder
        app.upstream.responder = lambda request, n: (lock.acquire(), inner(request, n))[1]
        # release the lock the moment the recorder gives up, so the chunk write that follows works
        released = []

        class Release(logging.Handler):
            def emit(self, record):
                if "usage event not recorded" in record.getMessage() and not released:
                    released.append(1)
                    lock.release()

        handler = Release(logging.WARNING)
        logging.getLogger("mcp_perplexity_pro.usage").addHandler(handler)
        try:
            locked = await run(app, items=texts(("b", "two")))
        finally:
            logging.getLogger("mcp_perplexity_pro.usage").removeHandler(handler)
            lock.close()
        assert released and (locked.embedded_chunks, baseline.embedded_chunks) == (1, 1)
        assert len(await events(app)) == 1  # the second event was lost, the call was not
        assert len(await chunks(app)) == 2
    finally:
        await close_app(app)


async def test_a_task_cancelled_mid_call_leaves_no_event_and_no_error(world):
    async def hang(request, n):
        await asyncio.sleep(30)

    app = await world(hang)
    task = asyncio.create_task(run(app))
    await asyncio.wait_for(app.upstream.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await events(app) == [] and await chunks(app) == []


async def test_a_task_cancelled_after_the_response_still_stores_the_event_and_the_chunks(
    world, monkeypatch
):
    """Mutation check: running the chunk write without ``shielded_write`` turns this red."""
    app = await world()
    real = embeddings._write_complete_items
    started = asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await asyncio.sleep(0.2)  # the cancel arrives while the write is in progress
        return await real(*args, **kwargs)

    monkeypatch.setattr(embeddings, "_write_complete_items", slow)
    task = asyncio.create_task(run(app))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.5)  # the shielded write finishes on its own
    assert [e[2] for e in await events(app)] == ["ok"]
    assert len(await chunks(app)) == 1


async def test_no_stored_column_and_no_log_record_contains_the_text(world, caplog):
    app = await world()
    with caplog.at_level(logging.DEBUG):
        await run(app, items=texts((SECRET, SECRET)))
    async with app.engine.connect() as conn:
        from sqlalchemy import text

        stored = json.dumps(
            [[str(v) for v in r] for r in await conn.execute(text("SELECT * FROM usage_events"))]
        )
    own = "\n".join(
        logging.Formatter().format(r)
        for r in caplog.records
        if r.name.startswith("mcp_perplexity_pro")
    )  # a library's own DEBUG statement log is the redacting handler's job (test_log_setup)
    assert SECRET not in stored and SECRET not in own

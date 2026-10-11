"""Task 4.1 (py-search-api): ``search.run_search`` records every request through
``costed.costed_call`` against a real engine and a ``MockTransport``.

Every test that makes two or more successful calls in one database serves a different fixture
(distinct ``id``) to each: the partial unique index ``uq_usage_events_api_request_id`` keeps one
``ok`` event per ``(api, request_id)`` and would silently drop the second.
"""

import asyncio
import json
import logging
from types import SimpleNamespace

import httpx2
import pytest
from fixture_support import FIXTURE_DIR
from sqlalchemy import text
from usage_support import DbLock, Upstream

from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.search import TOOL, SearchOptions, build_request, run_search
from mcp_perplexity_pro.storage.engine import create_engine_for, database_path
from mcp_perplexity_pro.storage.migrate import migrate
from mcp_perplexity_pro.storage.session import unit_of_work

KEY = "test-dummy-api-key"
BUSY = 0.4
SECRET_QUERY = "zq-distinctive-secret-query-7781"


def fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def serve(name, status=200):
    return lambda request, n: httpx2.Response(status, json=fixture(name))


def serve_body(body, status=200, headers=None):
    return lambda request, n: httpx2.Response(status, json=body, headers=headers)


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder, **settings):
        cfg = make_settings(db_busy_timeout=BUSY, max_attempts=1, **settings)
        migrate(cfg)
        engine = create_engine_for(cfg)
        upstream = Upstream(responder)
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
        client = PerplexityClient(cfg, http=http)
        made.append((http, engine))
        return SimpleNamespace(settings=cfg, client=client, engine=engine), upstream, cfg

    yield build
    for http, engine in made:
        await http.aclose()
        await engine.dispose()


async def events(app):
    async with app.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT tool, api, status, model, preset, request_id, project_name, "
                "cost_nano_usd, cost_source, price_table, usage_json FROM usage_events ORDER BY id"
            )
        )
        return [tuple(r) for r in rows]


async def search(app, *, query="q", search_type="fast", project="alpha", body=None, **kwargs):
    options = SearchOptions(query=query, search_type=search_type, **kwargs)
    return await run_search(
        app,
        project=project,
        body=body if body is not None else build_request(options),
        search_type=search_type,
    )


# --- one event per request ---------------------------------------------------------------------


async def test_a_fast_search_is_one_ok_event_with_the_computed_cost(world):
    app, _, _ = await world(serve("search_fast_single.json"))
    costed = await search(app, query="python asyncio taskgroup", max_results=5)
    raw = fixture("search_fast_single.json")
    assert costed.status == "ok" and costed.project == "alpha"
    ((tool, api, status, model, preset, rid, project, nano, source, table, _),) = await events(app)
    assert (tool, api, status, model, preset, rid, project) == (
        TOOL, "search", "ok", None, None, raw["id"], "alpha",
    )  # fmt: skip
    assert (nano, source, table) == (1_000_000, "computed", "2026-10-09")


async def test_a_web_search_costs_five_million_nano(world):
    app, _, _ = await world(serve("search_web_single.json"))
    await search(app, search_type="web")
    assert (await events(app))[0][7] == 5_000_000


@pytest.mark.parametrize(
    ("name", "query"),
    [
        ("search_fast_multi_query.json", ["a", "b", "c"]),  # one billing unit for three queries
        ("search_fast_date_range_empty.json", "python release"),  # empty results are billed
    ],
)
async def test_multi_query_and_empty_results_are_one_unit(world, name, query):
    app, _, _ = await world(serve(name))
    await search(app, query=query)
    ((*_, status, _m, _p, _r, _pn, nano, source, _t, _u),) = await events(app)
    assert (status, nano, source) == ("ok", 1_000_000, "computed")


async def test_an_inline_usage_object_is_stored_as_received_and_not_read_as_a_cost(world):
    body = {**fixture("search_fast_single.json"), "usage": {"cost": {"total_cost": 0.9}}}
    app, _, _ = await world(serve_body(body))
    await search(app)
    ((*_, nano, source, _t, usage_json),) = await events(app)
    assert (nano, source) == (1_000_000, "computed")
    assert json.loads(usage_json) == {"cost": {"total_cost": 0.9}}


# --- failures --------------------------------------------------------------------------------


async def test_the_apis_400_for_too_many_queries_is_a_cost_zero_failure_event(world):
    app, _, _ = await world(serve("search_too_many_queries_400.json", 400))
    body = {"query": ["a1", "b2", "c3", "d4", "e5", "f6"], "search_type": "fast"}
    with pytest.raises(PerplexityError) as caught:
        await search(app, body=body)  # a hand-built body skips the local validation
    assert caught.value.category == "invalid_request"
    ((*_, status, _m, _p, rid, _pn, nano, source, _t, _u),) = await events(app)
    assert (status, rid, nano, source) == ("invalid_request", None, 0, "none")


@pytest.mark.parametrize(
    ("responder", "category"),
    [
        (serve_body({"error": {"message": "slow"}}, 429, {"Retry-After": "600"}), "rate_limited"),
        (serve_body({"error": {"message": "down"}}, 503), "upstream_failure"),
        (
            lambda request, n: (_ for _ in ()).throw(httpx2.ReadTimeout("t", request=request)),
            "network_timeout",
        ),
        (serve_body({"id": "x"}), "unexpected_response"),
    ],
    ids=["429", "503", "timeout", "no-results"],
)
async def test_each_failure_is_one_event_with_its_category_and_no_cost(world, responder, category):
    app, _, _ = await world(responder)
    with pytest.raises(PerplexityError) as caught:
        await search(app)
    assert caught.value.category == category
    ((*_, status, _m, _p, _r, _pn, nano, source, _t, _u),) = await events(app)
    assert (status, nano, source) == (category, 0, "none")


async def test_a_local_validation_failure_records_nothing_and_creates_no_project(world):
    app, upstream, _ = await world(serve("search_fast_single.json"))
    with pytest.raises(PerplexityError):
        await search(app, query="   ")
    assert upstream.calls == 0 and await events(app) == []
    async with app.engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM projects"))).scalar_one() == 0


async def test_a_project_created_before_a_failing_call_survives_it(world):
    app, _, _ = await world(serve_body({"error": {"message": "down"}}, 503))
    with pytest.raises(PerplexityError):
        await search(app, project="beta")
    async with unit_of_work(app.engine, write=False) as session:
        assert (await _lookup(session, "beta")) is not None


async def _lookup(session, name):
    row = await session.execute(text("SELECT id FROM projects WHERE name = :n"), {"n": name})
    return row.first()


# --- order, isolation, cancellation -----------------------------------------------------------


async def test_another_connection_can_write_while_the_upstream_call_is_in_flight(world):
    app, upstream, cfg = await world(serve("search_fast_single.json"))
    seen = []
    inner = upstream.responder

    def during(request, n):
        lock = DbLock(database_path(cfg.data_dir))
        try:
            lock.acquire()
            seen.append("acquired")
        finally:
            lock.close()
        return inner(request, n)

    upstream.responder = during
    await search(app)
    assert seen == ["acquired"]


async def test_a_database_locked_past_the_busy_timeout_leaves_the_result_unchanged(world, caplog):
    first = fixture("search_fast_single.json")
    second = fixture("search_web_single.json")  # a distinct id, so the second event is storable
    bodies = [first, second]
    app, upstream, cfg = await world(lambda request, n: httpx2.Response(200, json=bodies[n - 1]))
    baseline = (await search(app)).result.model_dump()
    lock = DbLock(database_path(cfg.data_dir))
    inner = upstream.responder
    upstream.responder = lambda request, n: (lock.acquire(), inner(request, n))[1]
    try:
        with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.usage"):
            locked = await search(app)
    finally:
        lock.close()
    assert len(locked.result.results) == len(second["results"]) and baseline["results"]
    assert len(await events(app)) == 1  # the second event was lost, the call was not
    assert KEY not in caplog.text


async def test_a_task_cancelled_mid_call_leaves_no_event_and_no_error(world):
    async def hang(request, n):
        await asyncio.sleep(30)

    app, upstream, _ = await world(hang)
    task = asyncio.create_task(search(app))
    await asyncio.wait_for(upstream.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await events(app) == []


async def test_the_query_text_is_in_no_stored_column_and_no_log(world, caplog):
    app, _, _ = await world(serve("search_fast_single.json"))
    with caplog.at_level(logging.DEBUG):
        await search(app, query=SECRET_QUERY)
    async with app.engine.connect() as conn:
        rows = await conn.execute(text("SELECT * FROM usage_events"))
        stored = json.dumps([[str(v) for v in r] for r in rows])
    assert SECRET_QUERY not in stored and SECRET_QUERY not in caplog.text

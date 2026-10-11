"""Task 1.3 (py-search-api): the shared costed call, driven directly with a scripted ``call``."""

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from mcp_perplexity_pro.costed import Recording, costed_call
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate
from mcp_perplexity_pro.usage import computed_usage


@pytest.fixture
async def app(make_settings):
    settings = make_settings()
    migrate(settings)
    engine = create_engine_for(settings)
    yield SimpleNamespace(settings=settings, engine=engine)
    await engine.dispose()


async def rows(app):
    async with app.engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT tool, api, status, request_id, cost_nano_usd, cost_source, usage_json "
                "FROM usage_events ORDER BY id"
            )
        )
        return [tuple(r) for r in result]


async def run(app, call, record, **kwargs):
    return await costed_call(
        app,
        tool="perplexity_x",
        api="search",
        project="alpha",
        preset=None,
        call=call,
        record=record,
        **kwargs,
    )


async def test_a_raising_interpreter_records_exactly_one_unexpected_response_event(app):
    async def call():
        return {"id": "r1"}

    def broken(_):
        raise KeyError("boom")

    with pytest.raises(PerplexityError) as caught:
        await run(app, call, broken)
    assert caught.value.category == "unexpected_response"
    assert await rows(app) == [
        ("perplexity_x", "search", "unexpected_response", None, 0, "none", None)
    ]


async def test_a_parsed_usage_is_stored_as_given_and_the_costed_carries_the_recording(app):
    async def call():
        return {"id": "r1"}

    usage = computed_usage(1_000_000)
    costed = await run(app, call, lambda r: Recording("ok", usage, None, None, r["id"]))
    assert costed.recording is not None and costed.recording.usage is usage
    assert costed.status == "ok" and costed.project == "alpha" and costed.result == {"id": "r1"}
    ((tool, api, status, request_id, cost, source, _),) = await rows(app)
    assert (tool, api, status, request_id, cost, source) == (
        "perplexity_x",
        "search",
        "ok",
        "r1",
        1_000_000,
        "computed",
    )


async def test_an_interpreter_returning_none_records_nothing(app):
    async def call():
        return 1

    costed = await run(app, call, lambda _: None)
    assert costed.status is None and costed.recording is None
    assert await rows(app) == []


async def test_a_failed_call_records_its_category_and_reraises(app):
    async def call():
        raise PerplexityError("upstream_failure", "down")

    with pytest.raises(PerplexityError):
        await run(app, call, lambda _: None)
    assert [r[2] for r in await rows(app)] == ["upstream_failure"]


async def test_an_agent_interpreter_failure_is_now_one_unexpected_response_event(app):
    """Intended change of py-search-api 1.3 (not a regression): before the extraction an
    exception while interpreting an Agent response escaped as an ``internal_error`` and the billed
    run recorded nothing; now it is one ``unexpected_response`` event and that category."""

    class Run:
        def model_dump(self, **_):
            raise RuntimeError("cannot dump")

    from mcp_perplexity_pro.agent import run_costed

    app.client = SimpleNamespace()

    async def create_run(body, *, background):
        return Run()

    app.client.create_run = create_run
    with pytest.raises(PerplexityError) as caught:
        await run_costed(app, tool="t", project="alpha", body={}, preset="fast", background=False)
    assert caught.value.category == "unexpected_response"
    assert [r[2] for r in await rows(app)] == ["unexpected_response"]

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


# --- model-matrix 2.1 (design D7): recording without a project ---------------------------------


async def counts(app):
    async with app.engine.connect() as conn:
        projects = (await conn.execute(text("SELECT COUNT(*) FROM projects"))).scalar_one()
        events = (
            await conn.execute(
                text("SELECT project_id, project_name FROM usage_events ORDER BY id")
            )
        ).all()
        return projects, [tuple(e) for e in events]


async def run_unscoped(app, call, record, **kwargs):
    return await costed_call(
        app,
        tool="model_matrix",
        api="agent",
        project=None,
        preset=None,
        call=call,
        record=record,
        unscoped=True,
        **kwargs,
    )


async def test_an_unscoped_call_creates_no_project_and_its_event_has_none(app):
    async def call():
        return {"id": "r1"}

    costed = await run_unscoped(app, call, lambda r: Recording("ok", None, "m", None, r["id"]))
    assert costed.project is None and costed.status == "ok"
    assert await counts(app) == (0, [(None, None)])
    ((tool, api, status, *_),) = await rows(app)
    assert (tool, api, status) == ("model_matrix", "agent", "ok")


@pytest.mark.parametrize("resolve_project", [True, False])
async def test_unscoped_implies_no_project_resolution_whatever_resolve_project_says(
    app, resolve_project
):
    async def call():
        return 1

    await run_unscoped(app, call, lambda _: Recording("ok"), resolve_project=resolve_project)
    assert (await counts(app))[0] == 0


async def test_an_unscoped_call_does_not_validate_or_use_a_project_name(app):
    async def call():
        return 1

    costed = await costed_call(
        app,
        tool="model_matrix",
        api="agent",
        project="not a valid project name!",  # would be invalid_request if it were validated
        preset=None,
        call=call,
        record=lambda _: Recording("ok"),
        unscoped=True,
    )
    assert costed.project is None
    assert await counts(app) == (0, [(None, None)])


async def test_a_failed_unscoped_call_records_its_category_with_no_project(app):
    async def call():
        raise PerplexityError("rate_limited", "slow down")

    with pytest.raises(PerplexityError):
        await run_unscoped(app, call, lambda _: None)
    assert await counts(app) == (0, [(None, None)])
    assert [r[2] for r in await rows(app)] == ["rate_limited"]


async def test_perplexity_usage_groups_an_unscoped_event_under_none(app):
    from mcp_perplexity_pro.storage.session import unit_of_work
    from mcp_perplexity_pro.usage_report import usage_report

    async def call():
        return 1

    await run_unscoped(app, call, lambda _: Recording("ok", computed_usage(1_000_000)))
    await run(app, call, lambda _: Recording("ok"))  # a scoped one, for contrast
    async with unit_of_work(app.engine, write=False) as session:
        report = await usage_report(session, group_by="project")
    assert {g.key: g.measures.calls for g in report.groups} == {"(none)": 1, "alpha": 1}
    assert report.totals.calls == 2


async def test_a_scoped_call_still_resolves_validates_and_returns_its_project_name(app):
    async def call():
        return 1

    costed = await run(app, call, lambda _: Recording("ok"))
    assert costed.project == "alpha"
    assert await counts(app) == (1, [(1, "alpha")])
    default = await costed_call(
        app,
        tool="t",
        api="search",
        project=None,
        preset=None,
        call=call,
        record=lambda _: Recording("ok"),
    )
    assert default.project == "default"  # None still means the default project when scoped
    with pytest.raises(PerplexityError) as caught:
        await costed_call(
            app,
            tool="t",
            api="search",
            project="not a valid project name!",
            preset=None,
            call=call,
            record=lambda _: None,
        )
    assert caught.value.category == "invalid_request"

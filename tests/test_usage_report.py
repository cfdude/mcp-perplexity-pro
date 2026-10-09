"""Task 5.1: the report queries over hand-built events (usage-reporting "Exact totals",
"Grouping", "Group ordering and limit", "Report filters")."""

from datetime import date

import pytest
from sqlalchemy import text

from mcp_perplexity_pro.storage.session import unit_of_work
from mcp_perplexity_pro.usage import format_usd
from mcp_perplexity_pro.usage_report import GROUP_EXPRESSIONS, usage_report

COLUMNS = (
    "created_at, tool, api, status, model, project_name, input_tokens, output_tokens, "
    "total_tokens, cost_nano_usd, cost_source"
)


async def add(
    engine,
    *,
    at="2026-10-08 12:00:00",
    tool="t",
    api="agent",
    status="ok",
    model="m",
    project="alpha",
    inp=None,
    out=None,
    total=None,
    cost=0,
    source="reported",
):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"INSERT INTO usage_events ({COLUMNS}) VALUES "
                "(:at, :tool, :api, :status, :model, :project, :inp, :out, :total, :cost, :source)"
            ),
            {
                "at": at,
                "tool": tool,
                "api": api,
                "status": status,
                "model": model,
                "project": project,
                "inp": inp,
                "out": out,
                "total": total,
                "cost": cost,
                "source": source,
            },
        )


async def report(engine, **kwargs):
    async with unit_of_work(engine, write=False) as session:
        return await usage_report(session, **kwargs)


async def test_totals_are_exact_integer_sums(storage_engine):
    for cost in (210_000, 20_000, 1_000_000):
        await add(storage_engine, cost=cost, inp=10, out=2, total=12)
    result = await report(storage_engine)
    assert result.totals.cost_nano_usd == 1_230_000
    assert format_usd(result.totals.cost_nano_usd) == "0.00123"
    assert (result.totals.input_tokens, result.totals.output_tokens) == (30, 6)
    assert result.totals.total_tokens == 36


async def test_unknown_token_counts_add_zero(storage_engine):
    await add(storage_engine, inp=5, out=None, total=None)
    await add(storage_engine, inp=None, out=None, total=None)
    totals = (await report(storage_engine)).totals
    assert (totals.calls, totals.input_tokens, totals.output_tokens, totals.total_tokens) == (
        2,
        5,
        0,
        0,
    )


async def test_an_empty_history_is_zeros_and_no_groups(storage_engine):
    result = await report(storage_engine)
    assert result.totals == type(result.totals)(0, 0, 0, 0, 0, 0, 0, 0)
    assert (result.groups, result.groups_total, result.groups_truncated) == ([], 0, False)


async def test_five_events_with_two_errors(storage_engine):
    for status in ("ok", "ok", "ok", "rate_limited", "network_timeout"):
        await add(storage_engine, status=status)
    totals = (await report(storage_engine)).totals
    assert (totals.calls, totals.errors) == (5, 2)


async def test_date_bounds_are_inclusive_utc_days(storage_engine):
    await add(storage_engine, at="2026-10-07 23:59:59", cost=1)
    await add(storage_engine, at="2026-10-08 00:00:00", cost=2)
    await add(storage_engine, at="2026-10-08 23:59:59.999999", cost=4)
    await add(storage_engine, at="2026-10-09 00:00:00", cost=8)
    day = date(2026, 10, 8)
    assert (await report(storage_engine, since=day, until=day)).totals.cost_nano_usd == 6
    assert (await report(storage_engine, since=day)).totals.cost_nano_usd == 14
    assert (await report(storage_engine, until=day)).totals.cost_nano_usd == 7


async def test_microsecond_timestamps_written_by_the_recorder_are_bounded_correctly(storage_engine):
    await add(storage_engine, at="2026-10-08 00:00:00.000000", cost=1)
    await add(storage_engine, at="2026-10-07 23:59:59.999999", cost=2)
    day = date(2026, 10, 8)
    assert (await report(storage_engine, since=day, until=day)).totals.cost_nano_usd == 1


async def test_a_deleted_project_is_reportable_by_name_and_an_unknown_one_creates_nothing(
    storage_engine,
):
    await add(storage_engine, project="gone", cost=5)  # no such project row exists
    assert (await report(storage_engine, project="gone")).totals.cost_nano_usd == 5
    result = await report(storage_engine, project="never")
    assert result.totals.calls == 0
    async with storage_engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM projects"))).scalar_one() == 0


@pytest.mark.parametrize(
    ("group_by", "key_of"),
    [
        ("tool", lambda e: e["tool"]),
        ("api", lambda e: e["api"]),
        ("model", lambda e: e["model"]),
        ("project", lambda e: e["project"]),
        ("day", lambda e: e["at"][:10]),
    ],
)
async def test_grouping_by_each_of_the_five_values(storage_engine, group_by, key_of):
    events = [
        {
            "tool": "a",
            "api": "agent",
            "model": "m1",
            "project": "p1",
            "at": "2026-10-01 10:00:00",
            "cost": 1,
        },
        {
            "tool": "b",
            "api": "search",
            "model": "m2",
            "project": "p2",
            "at": "2026-10-02 10:00:00",
            "cost": 2,
        },
        {
            "tool": "b",
            "api": "search",
            "model": "m2",
            "project": "p2",
            "at": "2026-10-02 11:00:00",
            "cost": 4,
        },
    ]
    for event in events:
        await add(storage_engine, **event)
    result = await report(storage_engine, group_by=group_by)
    expected = {}
    for event in events:
        expected.setdefault(key_of(event), [0, 0])
        expected[key_of(event)][0] += 1
        expected[key_of(event)][1] += event["cost"]
    assert {g.key: [g.measures.calls, g.measures.cost_nano_usd] for g in result.groups} == expected
    assert result.groups_total == len(expected) and not result.groups_truncated


async def test_a_null_model_is_grouped_under_none(storage_engine):
    await add(storage_engine, model=None, cost=3)
    await add(storage_engine, model="m", cost=1)
    result = await report(storage_engine, group_by="model")
    assert [(g.key, g.measures.cost_nano_usd) for g in result.groups] == [("(none)", 3), ("m", 1)]


async def test_a_null_project_name_is_grouped_under_none(storage_engine):
    await add(storage_engine, project=None, cost=3)
    result = await report(storage_engine, group_by="project")
    assert [g.key for g in result.groups] == ["(none)"]


async def test_limit_cuts_groups_but_not_the_totals(storage_engine):
    for n, cost in enumerate((10, 50, 30, 40, 20)):
        await add(storage_engine, tool=f"t{n}", cost=cost)
    result = await report(storage_engine, limit=2)
    assert [(g.key, g.measures.cost_nano_usd) for g in result.groups] == [("t1", 50), ("t3", 40)]
    assert (result.groups_total, result.groups_truncated) == (5, True)
    assert result.totals.cost_nano_usd == 150 and result.totals.calls == 5


async def test_day_with_a_limit_keeps_the_latest_days_ascending(storage_engine):
    for day in range(1, 6):
        await add(storage_engine, at=f"2026-10-0{day} 09:00:00", cost=day)
    result = await report(storage_engine, group_by="day", limit=2)
    assert [g.key for g in result.groups] == ["2026-10-04", "2026-10-05"]
    assert (result.groups_total, result.groups_truncated) == (5, True)
    assert result.totals.calls == 5


async def test_day_groups_are_in_date_order_without_a_limit(storage_engine):
    for at in ("2026-10-03 01:00:00", "2026-10-01 01:00:00", "2026-10-02 01:00:00"):
        await add(storage_engine, at=at)
    result = await report(storage_engine, group_by="day")
    assert [g.key for g in result.groups] == ["2026-10-01", "2026-10-02", "2026-10-03"]


async def test_tied_costs_are_ordered_by_key(storage_engine):
    for tool in ("zeta", "alpha", "mid"):
        await add(storage_engine, tool=tool, cost=7)
    result = await report(storage_engine)
    assert [g.key for g in result.groups] == ["alpha", "mid", "zeta"]


async def test_computed_and_unknown_cost_calls_are_counted(storage_engine):
    await add(storage_engine, source="computed", cost=1_000_000)
    await add(storage_engine, source="reported", cost=5)
    await add(storage_engine, source="none", status="ok")  # a success nobody could price
    await add(storage_engine, source="none", status="rate_limited")  # an error
    totals = (await report(storage_engine)).totals
    assert (totals.calls_cost_computed, totals.calls_cost_unknown) == (1, 2)
    assert (totals.calls, totals.errors) == (4, 1)


async def test_group_measures_match_the_totals_measures(storage_engine):
    await add(storage_engine, tool="a", inp=3, out=1, total=4, cost=9, source="computed")
    await add(storage_engine, tool="a", status="rate_limited", source="none")
    (group,) = (await report(storage_engine)).groups
    assert group.measures == (await report(storage_engine)).totals


async def test_an_unknown_grouping_key_is_refused_by_the_query_function(storage_engine):
    for bad in ("colour", "", "tool; DROP TABLE usage_events", None, "project_name"):
        with pytest.raises(ValueError, match="group_by"):
            await report(storage_engine, group_by=bad)
    async with storage_engine.connect() as conn:  # nothing was executed
        assert (await conn.execute(text("SELECT count(*) FROM usage_events"))).scalar_one() == 0


@pytest.mark.parametrize("limit", [0, -1, True, "2"])
async def test_a_bad_limit_is_refused(storage_engine, limit):
    with pytest.raises(ValueError, match="limit"):
        await report(storage_engine, limit=limit)


async def test_until_at_the_last_representable_day_is_refused(storage_engine):
    with pytest.raises(ValueError, match="until"):
        await report(storage_engine, until=date.max)


def test_the_whitelist_is_exactly_the_five_documented_groupings():
    assert set(GROUP_EXPRESSIONS) == {"tool", "api", "model", "project", "day"}
    assert GROUP_EXPRESSIONS["project"] == "project_name"  # never project_id (design D5)


async def test_a_hostile_project_filter_is_a_bound_value_not_sql(storage_engine):
    await add(storage_engine, project="alpha", cost=1)
    result = await report(storage_engine, project="alpha' OR '1'='1")
    assert result.totals.calls == 0

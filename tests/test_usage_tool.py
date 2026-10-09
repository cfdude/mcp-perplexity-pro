"""Task 5.2: the ``perplexity_usage`` tool through the server factory (usage-reporting "Spend
report tool", "Report filters", "Exact totals", "Grouping", "Group ordering and limit")."""

import httpx2
import jsonschema
import pytest
from fastmcp import Client
from sqlalchemy import text
from usage_support import table_counts

from mcp_perplexity_pro.errors import ALL_CATEGORIES
from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.usage import computed_usage, record_usage

TOOL = "perplexity_usage"


@pytest.fixture
async def server(make_settings, storage_engine):
    def no_upstream(request):
        raise AssertionError("perplexity_usage must not call the upstream API")

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(no_upstream))
    yield build_server(make_settings(), http, storage_engine)
    await http.aclose()


async def call(server, **arguments):
    async with Client(server) as client:
        return await client.call_tool(TOOL, arguments, raise_on_error=False)


async def add(engine, at, cost, *, tool="t", project="alpha", status="ok", source="reported"):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO usage_events (created_at, tool, api, status, project_name, "
                "total_tokens, cost_nano_usd, cost_source) "
                "VALUES (:at, :tool, 'agent', :status, :p, 7, :cost, :src)"
            ),
            {"at": at, "tool": tool, "status": status, "p": project, "cost": cost, "src": source},
        )


async def test_an_empty_history_is_zeros_and_not_an_error(server):
    result = await call(server)
    assert not result.is_error
    data = result.structured_content
    assert data["totals"]["calls"] == 0 and data["totals"]["cost_usd"] == "0"
    assert data["groups"] == [] and data["groups_truncated"] is False
    assert data["group_by"] == "tool" and data["limit"] == 20
    assert "0 call(s)" in result.content[0].text


async def test_totals_groups_and_text_for_hand_built_events(server, storage_engine):
    await add(storage_engine, "2026-10-08 10:00:00", 210_000)
    await add(storage_engine, "2026-10-08 11:00:00", 20_000, tool="u")
    await add(storage_engine, "2026-10-08 12:00:00", 1_000_000, tool="t")
    result = await call(server)
    data = result.structured_content
    assert data["totals"]["cost_nano_usd"] == 1_230_000 and data["totals"]["cost_usd"] == "0.00123"
    assert [(g["key"], g["calls"], g["cost_usd"]) for g in data["groups"]] == [
        ("t", 2, "0.00121"),
        ("u", 1, "0.00002"),
    ]
    text_out = result.content[0].text
    assert "0.00123 USD" in text_out and "lower bound" in text_out
    assert "t | 2 | 0 | 14 | 0.00121" in text_out


async def test_filters_dates_and_deleted_projects_through_the_tool(server, storage_engine):
    await add(storage_engine, "2026-10-07 23:59:59", 1)
    await add(storage_engine, "2026-10-08 00:00:00", 2, project="gone")
    result = await call(server, since="2026-10-08", until="2026-10-08", project="gone")
    assert result.structured_content["totals"]["cost_nano_usd"] == 2
    assert result.structured_content["since"] == "2026-10-08"
    never = await call(server, project="never-existed")
    assert not never.is_error and never.structured_content["totals"]["calls"] == 0


async def test_limit_truncation_is_stated(server, storage_engine):
    for n in range(5):
        await add(storage_engine, f"2026-10-0{n + 1} 10:00:00", n + 1, tool=f"t{n}")
    result = await call(server, limit=2)
    data = result.structured_content
    assert (len(data["groups"]), data["groups_total"], data["groups_truncated"]) == (2, 5, True)
    assert data["totals"]["calls"] == 5
    assert "Showing 2 of 5 groups" in result.content[0].text


@pytest.mark.parametrize(
    "arguments",
    [
        {"since": "2026-13-01"},
        {"since": "2026-10-09T00:00"},
        {"since": "20261009"},
        {"until": "2026-10-9"},
        {"until": "2026-W41-1"},
        {"until": "٢٠٢٦-١٠-٠٩"},  # Arabic-Indic digits are not YYYY-MM-DD
        {"until": "0000-01-01"},
        {"until": "9999-12-31"},
        {"since": "2026-10-09", "until": "2026-10-01"},
        {"project": "../etc"},
        {"project": "pplx-" + "abcdefghijklmnopqrstuvwx"},
        {"group_by": "colour"},
        {"limit": 0},
        {"limit": 201},
        {"limit": -5},
    ],
    ids=lambda a: "-".join(f"{k}={v}" for k, v in a.items())[:40],
)
async def test_bad_arguments_are_invalid_request_never_internal_error(server, arguments):
    result = await call(server, **arguments)
    assert result.is_error
    category = result.structured_content["category"]
    assert category == "invalid_request"
    assert category in ALL_CATEGORIES and category != "internal_error"


async def test_the_boundary_values_are_accepted(server):
    for arguments in (
        {"limit": 1},
        {"limit": 200},
        {"until": "9999-12-30"},
        {"since": "0001-01-01"},
    ):
        assert not (await call(server, **arguments)).is_error, arguments


async def test_the_tool_is_advertised_read_only_with_the_lower_bound_wording(server):
    async with Client(server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    description = " ".join(tool.description.split())  # line wrapping is not part of the wording
    assert "error calls count cost 0 and may have been billed" in description
    assert "lower bound" in description
    props = tool.input_schema["properties"]
    assert set(props) == {"project", "since", "until", "group_by", "limit"}
    assert props["group_by"]["enum"] == ["tool", "api", "model", "project", "day"]
    assert all(p.get("description") for p in props.values())
    assert not tool.input_schema.get("required")


async def test_structured_content_validates_against_the_advertised_schema(server, storage_engine):
    await add(storage_engine, "2026-10-08 10:00:00", 5, source="computed")
    await add(storage_engine, "2026-10-08 10:00:01", 0, status="rate_limited", source="none")
    async with Client(server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
        for arguments in ({}, {"group_by": "day"}, {"group_by": "model", "project": "alpha"}):
            result = await client.call_tool(TOOL, arguments)
            jsonschema.validate(result.structured_content, tool.output_schema)
        totals = (await client.call_tool(TOOL, {})).structured_content["totals"]
    assert (totals["calls_cost_computed"], totals["calls_cost_unknown"]) == (1, 1)
    assert totals["errors"] == 1


async def test_a_call_changes_no_row_and_creates_no_project(server, storage_engine):
    await add(storage_engine, "2026-10-08 10:00:00", 5)
    await record_usage(storage_engine, tool="t", api="search", usage=computed_usage(1_000_000))
    before = await table_counts(storage_engine, "projects", "usage_events")
    for arguments in ({}, {"project": "ghost"}, {"group_by": "project"}, {"limit": 0}):
        await call(server, **arguments)
    assert await table_counts(storage_engine, "projects", "usage_events") == before

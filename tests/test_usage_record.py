"""Task 3.4: ``record_usage`` (usage-recording requirements; design D6 and D8)."""

import json
import logging
from datetime import UTC, datetime

import pytest
from fixture_support import FIXTURE_DIR
from sqlalchemy import text

from mcp_perplexity_pro.storage.projects import get_or_create_project
from mcp_perplexity_pro.storage.session import unit_of_work
from mcp_perplexity_pro.usage import (
    MAX_USAGE_JSON,
    ToolCallUsage,
    Usage,
    computed_usage,
    record_usage,
    usage_from_agent_response,
)

KEY = "pplx-" + "Zy9_" * 8  # key-shaped
OTHER = "pplx-" + "Qq7-" * 8


def fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


async def rows(engine):
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT * FROM usage_events ORDER BY id"))
        return [dict(r._mapping) for r in result]


async def scalar(engine, sql):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql))).scalar_one()


@pytest.fixture
def fast():
    return fixture("agent_fast.json")


async def record(engine, **overrides):
    values = {"tool": "t", "api": "agent"}
    values.update(overrides)
    return await record_usage(engine, **values)


# --- identity and outcome ------------------------------------------------------------------


async def test_a_successful_call_stores_one_event_with_every_identity_field(storage_engine, fast):
    async with unit_of_work(storage_engine) as session:
        await get_or_create_project(session, "alpha")
    fixed = datetime(2026, 10, 9, 12, 30, 45, 123456)
    stored = await record_usage(
        storage_engine,
        tool="research",
        api="agent",
        usage=fast["usage"],
        model=fast["model"],
        preset="fast",
        request_id=fast["id"],
        project="alpha",
        latency_ms=812,
        clock=lambda: fixed,
    )
    assert stored is True
    (row,) = await rows(storage_engine)
    assert row["created_at"] == "2026-10-09 12:30:45.123456"  # naive UTC, microseconds kept
    assert (row["tool"], row["api"], row["status"]) == ("research", "agent", "ok")
    assert (row["model"], row["preset"]) == ("openai/gpt-6-luna", "fast")
    assert row["request_id"] == fast["id"] and row["latency_ms"] == 812
    assert row["project_name"] == "alpha"
    assert row["project_id"] == await scalar(storage_engine, "SELECT id FROM projects")
    assert (row["input_tokens"], row["output_tokens"], row["total_tokens"]) == (3426, 30, 3456)
    assert (row["cache_creation_tokens"], row["cache_read_tokens"]) == (1643, 1780)
    assert (row["cached_tokens"], row["reasoning_tokens"]) == (1780, 0)
    assert (row["cost_nano_usd"], row["cost_source"], row["currency"]) == (
        1_250_000,
        "reported",
        "USD",
    )
    assert row["cache_creation_cost_nano"] == 210_000 and row["price_table"] is None
    assert json.loads(row["tool_calls_json"]) == {
        "search_web": {"invocations": 1, "cost_nano": 1_000_000}
    }
    assert json.loads(row["usage_json"]) == fast["usage"]  # the object as received


async def test_the_default_clock_stamps_naive_utc_with_microseconds(storage_engine):
    await record(storage_engine)
    (row,) = await rows(storage_engine)
    stamp = datetime.fromisoformat(row["created_at"])
    assert stamp.tzinfo is None and "." in row["created_at"]
    assert abs((datetime.now(UTC).replace(tzinfo=None) - stamp).total_seconds()) < 5


async def test_a_failed_call_is_stored_with_cost_zero_and_source_none(storage_engine):
    assert await record(storage_engine, status="rate_limited", project="alpha") is True
    (row,) = await rows(storage_engine)
    assert row["status"] == "rate_limited"
    assert (row["cost_nano_usd"], row["cost_source"]) == (0, "none")
    assert row["input_tokens"] is None and row["usage_json"] is None


async def test_an_unexpected_response_with_a_reported_cost_keeps_it(storage_engine, fast):
    await record(storage_engine, status="unexpected_response", usage=fast["usage"])
    (row,) = await rows(storage_engine)
    assert (row["status"], row["cost_nano_usd"], row["cost_source"]) == (
        "unexpected_response",
        1_250_000,
        "reported",
    )


@pytest.mark.parametrize("api", ["chat", "", None, 5, "Agent"])
async def test_an_unknown_api_stores_nothing_and_logs_without_the_value(
    storage_engine, caplog, api
):
    with caplog.at_level(logging.WARNING):
        assert await record(storage_engine, api=api) is False
    assert await rows(storage_engine) == [] and len(caplog.records) == 1


@pytest.mark.parametrize("status", ["failed", "", None, 3, ["ok"], KEY])
async def test_an_unknown_status_stores_nothing_and_logs_redacted(storage_engine, caplog, status):
    with caplog.at_level(logging.WARNING):
        assert await record(storage_engine, status=status, secrets=[KEY]) is False
    assert await rows(storage_engine) == [] and len(caplog.records) == 1
    assert KEY not in caplog.text and "pplx-" not in caplog.text


async def test_a_missing_project_stores_null_id_with_the_name_and_creates_nothing(storage_engine):
    await record(storage_engine, project="ghost")
    (row,) = await rows(storage_engine)
    assert row["project_id"] is None and row["project_name"] == "ghost"
    assert await scalar(storage_engine, "SELECT count(*) FROM projects") == 0


async def test_a_call_without_a_project_stores_null_id_and_name(storage_engine):
    await record(storage_engine, project=None)
    (row,) = await rows(storage_engine)
    assert row["project_id"] is None and row["project_name"] is None


# --- redaction: one assertion per column ---------------------------------------------------


async def test_a_key_shaped_token_is_redacted_in_every_text_column(storage_engine, fast):
    usage = fast["usage"]
    usage["tool_calls_details"] = {f"web_{KEY}": usage["tool_calls_details"]["search_web"]}
    await record(
        storage_engine,
        tool=f"t-{KEY}",
        request_id=f"resp_{KEY}",
        model=f"m/{KEY}",
        preset=f"p-{OTHER}",
        project=f"proj-{KEY}",
        usage=usage,
    )
    (row,) = await rows(storage_engine)
    for column in ("tool", "request_id", "model", "preset", "project_name"):
        assert "pplx-" not in row[column], column
        assert "[redacted]" in row[column], column
    assert "pplx-" not in row["tool_calls_json"]
    assert "[redacted]" in row["tool_calls_json"]
    assert "pplx-" not in row["usage_json"]
    assert json.loads(row["usage_json"])["tool_calls_details"] == {
        "web_[redacted]": {"cost_usd": 0.001, "invocation": 1}
    }


async def test_a_configured_secret_is_redacted_and_the_json_stays_valid(storage_engine, fast):
    secret = "test-dummy-api-key"
    fast["usage"]["note"] = f"seen {secret}"
    await record(storage_engine, usage=fast["usage"], request_id=f"id-{secret}", secrets=[secret])
    (row,) = await rows(storage_engine)
    assert secret not in row["usage_json"] and secret not in row["request_id"]
    assert json.loads(row["usage_json"])["note"] == "seen [redacted]"


async def test_a_key_inside_usage_is_redacted_and_everything_else_survives(storage_engine, fast):
    fast["usage"]["note"] = f"x {KEY} y"
    await record(storage_engine, usage=fast["usage"])
    (row,) = await rows(storage_engine)
    stored = json.loads(row["usage_json"])
    assert stored.pop("note") == "x [redacted] y"
    original = fixture("agent_fast.json")["usage"]
    assert stored == original


# --- usage_json sanitizing ------------------------------------------------------------------


def marker(row):
    return json.loads(row["usage_json"])


async def test_an_unserializable_value_stores_the_marker_not_an_exception(storage_engine):
    usage = Usage(cost_nano_usd=5, cost_source="reported", input_tokens=9, raw={"x": {1, 2}})
    assert await record(storage_engine, usage=usage) is True
    (row,) = await rows(storage_engine)
    assert marker(row) == {"_truncated": True, "_reason": "unserializable", "_original_bytes": None}
    assert (row["cost_nano_usd"], row["input_tokens"]) == (5, 9)  # typed columns still filled


async def test_a_100000_level_nest_stores_the_marker(storage_engine):
    nest: dict = {}
    cursor = nest
    for _ in range(100_000):
        cursor["n"] = {}
        cursor = cursor["n"]
    assert await record(storage_engine, usage=Usage(raw=nest)) is True
    (row,) = await rows(storage_engine)
    assert marker(row)["_reason"] == "unserializable"


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
async def test_a_non_finite_number_stores_the_marker(storage_engine, fast, bad):
    fast["usage"]["weird"] = bad
    assert await record(storage_engine, usage=fast["usage"]) is True
    (row,) = await rows(storage_engine)
    assert marker(row)["_reason"] == "unserializable"
    assert row["input_tokens"] == 3426 and row["cost_nano_usd"] == 1_250_000


async def test_a_secret_that_breaks_the_json_stores_the_marker(storage_engine, fast):
    fast["usage"]["note"] = 'say "hi'
    assert await record(storage_engine, usage=fast["usage"], secrets=['"hi']) is True
    (row,) = await rows(storage_engine)
    assert marker(row)["_reason"] == "unserializable"
    assert row["input_tokens"] == 3426


async def test_an_oversize_usage_stores_the_marker_with_its_size(storage_engine, fast):
    fast["usage"]["padding"] = "x" * 20_000
    original = len(json.dumps(fast["usage"], separators=(",", ":")).encode())
    assert original > MAX_USAGE_JSON == 16384
    await record(storage_engine, usage=fast["usage"])
    (row,) = await rows(storage_engine)
    assert marker(row) == {"_truncated": True, "_reason": "oversize", "_original_bytes": original}
    assert (row["input_tokens"], row["cost_nano_usd"]) == (3426, 1_250_000)


async def test_a_usage_just_under_the_cap_is_kept(storage_engine, fast):
    base = len(json.dumps({**fast["usage"], "p": ""}, separators=(",", ":")).encode())
    fast["usage"]["p"] = "x" * (MAX_USAGE_JSON - base)
    await record(storage_engine, usage=fast["usage"])
    (row,) = await rows(storage_engine)
    assert len(row["usage_json"].encode()) == MAX_USAGE_JSON
    assert json.loads(row["usage_json"])["p"].startswith("xxx")


# --- usage argument: Usage | Mapping | None -------------------------------------------------


async def test_a_raw_mapping_is_stored_exactly_like_the_same_data_parsed_by_the_caller(
    storage_engine, fast
):
    await record(storage_engine, usage=fast["usage"], request_id="a")
    await record(storage_engine, usage=usage_from_agent_response(fast["usage"]), request_id="b")
    first, second = await rows(storage_engine)
    for key in ("id", "request_id", "created_at"):
        first.pop(key), second.pop(key)
    assert first == second


async def test_a_mapping_for_an_api_without_a_parser_is_kept_with_cost_source_none(storage_engine):
    await record(storage_engine, api="search", usage={"queries": 1, "total_cost": 0.005})
    (row,) = await rows(storage_engine)
    assert (row["cost_nano_usd"], row["cost_source"]) == (0, "none")
    assert json.loads(row["usage_json"]) == {"queries": 1, "total_cost": 0.005}


async def test_a_parser_that_raises_is_contained_and_the_event_is_stored_unpriced(
    storage_engine, monkeypatch, caplog
):
    from mcp_perplexity_pro import usage as usage_module

    def boom(_usage):
        raise RuntimeError(f"parser bug {KEY}")

    monkeypatch.setitem(usage_module._PARSERS, "agent", boom)
    with caplog.at_level(logging.WARNING):
        assert await record(storage_engine, usage={"a": 1}, secrets=[KEY]) is True
    (row,) = await rows(storage_engine)
    assert (row["cost_nano_usd"], row["cost_source"]) == (0, "none")
    assert KEY not in caplog.text and len(caplog.records) == 1


async def test_a_reported_cost_over_the_cap_is_stored_as_zero_unknown(storage_engine, fast):
    fast["usage"]["cost"]["total_cost"] = 9.3e9
    assert await record(storage_engine, usage=fast["usage"]) is True
    (row,) = await rows(storage_engine)
    assert (row["cost_nano_usd"], row["cost_source"]) == (0, "none")
    assert row["input_tokens"] == 3426


async def test_a_computed_event_stores_its_price_table(storage_engine):
    await record(storage_engine, api="search", usage=computed_usage(1_000_000))
    (row,) = await rows(storage_engine)
    assert (row["cost_nano_usd"], row["cost_source"], row["price_table"]) == (
        1_000_000,
        "computed",
        "2026-10-09",
    )


async def test_a_caller_built_usage_is_revalidated(storage_engine):
    bad = Usage(
        cost_nano_usd=-4,
        cost_source="reported",
        input_tokens=-1,
        tool_calls={"x": ToolCallUsage(10**13, -2)},
        price_table="2026-10-09",
    )
    assert await record(storage_engine, usage=bad) is True
    (row,) = await rows(storage_engine)
    assert (row["cost_nano_usd"], row["cost_source"], row["price_table"]) == (0, "none", None)
    assert row["input_tokens"] is None
    assert json.loads(row["tool_calls_json"]) == {"x": {"invocations": None, "cost_nano": None}}


@pytest.mark.parametrize("junk", ["usage", 5, [1, 2]])
async def test_a_usage_of_the_wrong_type_is_stored_unpriced(storage_engine, junk):
    assert await record(storage_engine, usage=junk) is True
    (row,) = await rows(storage_engine)
    assert (row["cost_nano_usd"], row["cost_source"], row["usage_json"]) == (0, "none", None)


async def test_non_text_identity_values_are_stored_as_unknown(storage_engine):
    await record(storage_engine, model={"a": 1}, preset=5, request_id=["x"], latency_ms="12")
    (row,) = await rows(storage_engine)
    assert (row["model"], row["preset"], row["request_id"], row["latency_ms"]) == (None,) * 4


# --- once per response ----------------------------------------------------------------------


async def test_a_completed_response_recorded_twice_leaves_one_row(storage_engine, caplog):
    poll = fixture("agent_background_poll.json")
    with caplog.at_level(logging.WARNING):
        for expected in (True, False):
            stored = await record(storage_engine, usage=poll["usage"], request_id=poll["id"])
            assert stored is expected
    assert len(await rows(storage_engine)) == 1
    assert caplog.records == []  # a duplicate is ignored without error, not logged as a failure


async def test_two_failed_calls_without_an_id_leave_two_rows(storage_engine):
    for _ in range(2):
        assert await record(storage_engine, status="network_timeout") is True
    assert len(await rows(storage_engine)) == 2


async def test_a_failure_never_blocks_a_later_success_with_the_same_id(storage_engine):
    await record(storage_engine, status="unexpected_response", request_id="r")
    assert await record(storage_engine, request_id="r") is True
    assert len(await rows(storage_engine)) == 2


async def test_the_same_id_under_another_api_is_a_different_response(storage_engine):
    await record(storage_engine, api="agent", request_id="r")
    assert await record(storage_engine, api="search", request_id="r") is True


# --- no content ------------------------------------------------------------------------------


async def test_only_usage_is_stored_never_output_text_or_the_prompt(storage_engine, fast):
    prompt = "What is the current stable version of Python? One sentence."
    await record(storage_engine, usage=fast["usage"], request_id=fast["id"], model=fast["model"])
    dump = json.dumps(await rows(storage_engine), default=str)
    assert "Python 3.14.8 is the current stable release" not in dump
    assert prompt not in dump and "snippet" not in dump and "python.org" not in dump


async def test_a_failure_while_building_the_event_is_contained(storage_engine, caplog):
    def broken_clock():
        raise RuntimeError(f"clock broke {KEY}")

    with caplog.at_level(logging.WARNING):
        assert await record(storage_engine, clock=broken_clock, secrets=[KEY]) is False
    assert await rows(storage_engine) == []
    assert len(caplog.records) == 1 and KEY not in caplog.text

"""Gate 2 fix-ups: recorder edge cases (non-USD and unpriced computed costs, failed-insert log
text, secrets that ``json.dumps`` escapes)."""

import json

import pytest
from sqlalchemy import text

from mcp_perplexity_pro.usage import Usage, record_usage

PAYLOAD = "PAYLOAD-MARKER-4f1c"


async def rows(engine):
    async with engine.connect() as conn:
        return [dict(r._mapping) for r in await conn.execute(text("SELECT * FROM usage_events"))]


async def test_a_non_usd_usage_is_never_stored_as_a_cost(storage_engine):
    parsed = Usage(cost_nano_usd=5_000_000, cost_source="reported", currency="EUR")
    await record_usage(storage_engine, tool="t", api="search", usage=parsed)
    (row,) = await rows(storage_engine)
    assert (row["cost_nano_usd"], row["cost_source"]) == (0, "none")


async def test_a_computed_cost_without_a_price_table_is_downgraded_to_none(storage_engine):
    parsed = Usage(cost_nano_usd=5_000_000, cost_source="computed", price_table=None)
    await record_usage(storage_engine, tool="t", api="search", usage=parsed)
    (row,) = await rows(storage_engine)
    assert (row["cost_nano_usd"], row["cost_source"], row["price_table"]) == (0, "none", None)


async def test_a_failed_insert_logs_no_statement_and_no_payload(storage_engine, caplog):
    async with storage_engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TRIGGER veto BEFORE INSERT ON usage_events "
                "BEGIN SELECT RAISE(ABORT, 'insert vetoed'); END"
            )
        )
    with caplog.at_level("WARNING"):
        stored = await record_usage(
            storage_engine, tool="t", api="agent", usage={"note": PAYLOAD}, request_id=PAYLOAD
        )
    assert stored is False
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "insert vetoed" in logged and "IntegrityError" in logged
    assert PAYLOAD not in logged and "[SQL:" not in logged and "[parameters:" not in logged
    assert "INSERT INTO" not in logged


async def test_a_secret_that_json_escapes_is_still_redacted_in_usage_json(storage_engine):
    secret = 'pä"ss\\word'
    usage = {"note": f"seen {secret} here", secret: 1, "nested": [{"k": secret}], "n": 3}
    await record_usage(storage_engine, tool="t", api="search", usage=usage, secrets=[secret])
    (row,) = await rows(storage_engine)
    raw = row["usage_json"]
    assert "pä" not in raw and "p\\u00e4" not in raw and "ss\\\\word" not in raw
    stored = json.loads(raw)
    assert stored["note"] == "seen [redacted] here" and stored["n"] == 3
    assert stored["nested"] == [{"k": "[redacted]"}] and stored["[redacted]"] == 1


@pytest.mark.parametrize("currency", ["USD"])
async def test_a_usd_reported_cost_still_stores(storage_engine, currency):
    parsed = Usage(cost_nano_usd=7, cost_source="reported", currency=currency)
    await record_usage(storage_engine, tool="t", api="search", usage=parsed)
    (row,) = await rows(storage_engine)
    assert (row["cost_nano_usd"], row["cost_source"]) == (7, "reported")

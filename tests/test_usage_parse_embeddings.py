"""Task 2.1 (py-embeddings): ``usage_from_embeddings_response`` and its registration."""

import json

import pytest
from fixture_support import FIXTURE_DIR
from sqlalchemy import text

from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate
from mcp_perplexity_pro.usage import _PARSERS, record_usage, usage_from_embeddings_response


def recorded(name):
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())["usage"]


@pytest.mark.parametrize(
    ("name", "nano", "tokens"),
    [
        ("embeddings_two_4b_dim256", 360, 12),
        ("embeddings_single_06b", 8, 2),
        ("embeddings_int8_explicit_06b", 8, 2),
        ("embeddings_unicode_06b", 56, 14),
    ],
)
def test_recorded_usage_is_reported_to_the_nano_usd(name, nano, tokens):
    usage = usage_from_embeddings_response(recorded(name))
    assert (usage.cost_nano_usd, usage.cost_source) == (nano, "reported")
    assert usage.input_tokens == tokens == usage.total_tokens
    assert usage.input_cost_nano == nano and usage.raw == recorded(name)


def test_float_repr_noise_rounds_to_the_nano():
    usage = usage_from_embeddings_response(
        {"prompt_tokens": 3, "cost": {"currency": "USD", "total_cost": 1.2000000000000002e-07}}
    )
    assert usage.cost_nano_usd == 120 and usage.cost_source == "reported"


def test_a_missing_cost_is_unknown_and_a_missing_currency_counts_as_usd():
    assert usage_from_embeddings_response({"prompt_tokens": 3}).cost_source == "none"
    usage = usage_from_embeddings_response({"cost": {"total_cost": 4e-9}})
    assert (usage.cost_nano_usd, usage.cost_source) == (4, "reported")


def test_a_non_usd_cost_is_cost_zero_source_none_and_tokens_are_kept():
    usage = usage_from_embeddings_response(
        {"prompt_tokens": 9, "total_tokens": 9, "cost": {"currency": "EUR", "total_cost": 1e-6}}
    )
    assert (usage.cost_nano_usd, usage.cost_source, usage.input_tokens) == (0, "none", 9)


@pytest.mark.parametrize("bad", [True, -1e-7, float("nan"), "0.1", 1e30, [1]])
def test_an_unusable_total_cost_is_unknown_while_tokens_survive(bad):
    usage = usage_from_embeddings_response(
        {"prompt_tokens": 7, "total_tokens": 7, "cost": {"currency": "USD", "total_cost": bad}}
    )
    assert (usage.cost_nano_usd, usage.cost_source) == (0, "none")
    assert usage.input_tokens == 7 and usage.total_tokens == 7


@pytest.mark.parametrize("raw", [None, "x", 5, [1]])
def test_a_missing_or_non_mapping_usage_is_empty(raw):
    usage = usage_from_embeddings_response(raw)
    assert usage.cost_source == "none" and usage.input_tokens is None


def test_the_parser_is_registered_for_the_embeddings_family():
    assert set(_PARSERS) == {"agent", "embeddings"}


async def test_record_usage_parses_a_raw_mapping_with_the_registered_parser(make_settings):
    settings = make_settings()
    migrate(settings)
    engine = create_engine_for(settings)
    try:
        stored = await record_usage(
            engine,
            tool="perplexity_embed",
            api="embeddings",
            usage=recorded("embeddings_two_4b_dim256"),
            model="pplx-embed-v1-4b",
        )
        assert stored
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT cost_nano_usd, cost_source, input_tokens FROM usage_events")
                )
            ).one()
        assert tuple(row) == (360, "reported", 12)
    finally:
        await engine.dispose()

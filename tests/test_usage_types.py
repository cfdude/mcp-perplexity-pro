"""Task 3.1: the recorder's data types and small helpers (design D7)."""

import dataclasses
import logging
from datetime import UTC, datetime

import pytest

from mcp_perplexity_pro.pricing import PRICES_AS_OF
from mcp_perplexity_pro.usage import ToolCallUsage, Usage, computed_usage, utcnow


def test_utcnow_is_naive_with_microseconds():
    stamps = [utcnow() for _ in range(50)]
    assert all(isinstance(s, datetime) and s.tzinfo is None for s in stamps)
    assert any(s.microsecond for s in stamps)  # not truncated to whole seconds
    assert abs((utcnow() - datetime.now(UTC).replace(tzinfo=None)).total_seconds()) < 5  # noqa: DTZ003


def test_computed_usage_states_its_source_and_price_table():
    usage = computed_usage(1_000_000)
    assert usage.cost_nano_usd == 1_000_000
    assert usage.cost_source == "computed"
    assert usage.price_table == "2026-10-09" == PRICES_AS_OF


def test_computed_usage_keeps_well_formed_facts():
    usage = computed_usage(
        4_000_000,
        input_tokens=1_000_000,
        total_tokens=1_000_000,
        tool_calls={"web_search": ToolCallUsage(invocations=1, cost_nano=2_500_000)},
    )
    assert usage.input_tokens == 1_000_000
    assert usage.output_tokens is None  # not given: unknown, not 0
    assert usage.tool_calls == {"web_search": ToolCallUsage(1, 2_500_000)}


@pytest.mark.parametrize(
    "facts",
    [
        {"input_tokens": "30"},
        {"input_tokens": True},
        {"input_tokens": -1},
        {"input_tokens": 10**13},
        {"input_cost_nano": -5},
        {"input_cost_nano": 10**13},
        {"tool_calls": "search_web"},
        {"tool_calls": {"x": "not a ToolCallUsage"}},
        {"not_a_field": 1},
    ],
)
def test_a_malformed_fact_becomes_unknown_instead_of_raising(facts, caplog):
    with caplog.at_level(logging.WARNING):
        usage = computed_usage(1_000_000, **facts)
    assert usage.cost_nano_usd == 1_000_000 and usage.cost_source == "computed"
    assert usage.input_tokens is None and usage.input_cost_nano is None
    assert usage.tool_calls == {}
    assert len(caplog.records) == 1


@pytest.mark.parametrize("cost", [-1, True, "5", None, 1.5, 10**12 + 1])
def test_an_unusable_computed_cost_is_a_cost_of_none_not_an_exception(cost):
    usage = computed_usage(cost, input_tokens=7)
    assert (usage.cost_nano_usd, usage.cost_source, usage.price_table) == (0, "none", None)
    assert usage.input_tokens == 7  # the facts survive


def test_both_dataclasses_are_immutable():
    for instance in (Usage(), ToolCallUsage()):
        field = dataclasses.fields(instance)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, field, 1)


def test_usage_defaults_mean_unknown():
    usage = Usage()
    assert (usage.cost_nano_usd, usage.cost_source) == (0, "none")
    assert usage.input_tokens is None and usage.raw is None and usage.currency == "USD"
    assert usage.tool_calls == {}

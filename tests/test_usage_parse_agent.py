"""Task 3.2: ``usage_from_agent_response`` against the recorded fixtures (design D7)."""

import copy
import json
import logging

import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.usage import ToolCallUsage, usage_from_agent_response


def fixture_usage(name):
    return json.loads((FIXTURE_DIR / name).read_text())["usage"]


@pytest.fixture
def fast():
    return fixture_usage("agent_fast.json")


def test_agent_fast_yields_every_reported_figure(fast):
    usage = usage_from_agent_response(fast)
    assert (usage.cost_nano_usd, usage.cost_source) == (1_250_000, "reported")
    assert (
        usage.input_tokens,
        usage.output_tokens,
        usage.total_tokens,
        usage.cache_creation_tokens,
        usage.cache_read_tokens,
        usage.cached_tokens,
        usage.reasoning_tokens,
    ) == (3426, 30, 3456, 1643, 1780, 1780, 0)
    assert usage.cache_creation_cost_nano == 210_000
    assert (usage.input_cost_nano, usage.output_cost_nano) == (0, 20_000)
    assert (usage.cache_read_cost_nano, usage.tool_calls_cost_nano) == (20_000, 1_000_000)
    assert usage.tool_calls == {"search_web": ToolCallUsage(1, 1_000_000)}
    assert usage.currency == "USD"
    assert usage.raw == fast


def test_an_absent_cache_creation_cost_is_unknown_not_zero():
    usage = usage_from_agent_response(fixture_usage("agent_background_poll.json"))
    assert usage.cache_creation_cost_nano is None
    assert usage.cost_nano_usd == 1_050_000 and usage.cost_source == "reported"


@pytest.mark.parametrize("value", [None, "usage", [1], 5, True])
def test_no_usage_or_a_non_mapping_is_cost_zero_source_none(value):
    usage = usage_from_agent_response(value)
    assert (usage.cost_nano_usd, usage.cost_source, usage.raw) == (0, "none", None)


@pytest.mark.parametrize(
    "total",
    [-0.1, "0.001", True, None, 1e30, 9.3e9, float("nan"), 10**5000, [0.1]],
    ids=lambda v: "10**5000" if isinstance(v, int) and v > 10**100 else repr(v),
)
def test_an_unusable_total_cost_is_none_and_keeps_raw(fast, total, caplog):
    fast["cost"]["total_cost"] = total
    with caplog.at_level(logging.WARNING):
        usage = usage_from_agent_response(fast)
    assert (usage.cost_nano_usd, usage.cost_source) == (0, "none")
    assert usage.raw is not None and usage.raw["input_tokens"] == 3426
    assert usage.input_tokens == 3426  # the other figures survive


def test_a_non_usd_currency_is_not_converted(fast, caplog):
    fast["cost"]["currency"] = "EUR"
    with caplog.at_level(logging.WARNING):
        usage = usage_from_agent_response(fast)
    assert (usage.cost_nano_usd, usage.cost_source, usage.currency) == (0, "none", "EUR")
    assert usage.cache_creation_cost_nano is None  # no USD figure is read from a EUR object
    assert len(caplog.records) == 1


def test_a_reported_zero_is_reported_not_none(fast):
    fast["cost"]["total_cost"] = 0
    usage = usage_from_agent_response(fast)
    assert (usage.cost_nano_usd, usage.cost_source) == (0, "reported")


def test_an_unknown_field_survives_in_raw(fast):
    fast["brand_new_field"] = {"x": 1}
    fast["cost"]["surprise"] = 7
    usage = usage_from_agent_response(fast)
    assert usage.raw["brand_new_field"] == {"x": 1}
    assert usage.raw["cost"]["surprise"] == 7
    assert usage.cost_nano_usd == 1_250_000


def test_the_input_is_not_mutated(fast):
    before = copy.deepcopy(fast)
    usage_from_agent_response(fast)
    assert fast == before


ALL_COSTS = {
    "cost_nano_usd": 0,
    "cost_source": "none",
    "input_cost_nano": None,
    "output_cost_nano": None,
    "cache_read_cost_nano": None,
    "cache_creation_cost_nano": None,
    "tool_calls_cost_nano": None,
}
# name -> (mutation of the fast usage object, the only figures that change, and to what)
MALFORMED = {
    "input_tokens_details as a list": (
        lambda u: u.__setitem__("input_tokens_details", [1]),
        {"cached_tokens": None, "cache_creation_tokens": None, "cache_read_tokens": None},
    ),
    "output_tokens as a string": (
        lambda u: u.__setitem__("output_tokens", "30"),
        {"output_tokens": None},
    ),
    "total_tokens negative": (lambda u: u.__setitem__("total_tokens", -1), {"total_tokens": None}),
    "input_tokens bool": (lambda u: u.__setitem__("input_tokens", True), {"input_tokens": None}),
    "input_tokens above the cap": (
        lambda u: u.__setitem__("input_tokens", 10**13),
        {"input_tokens": None},
    ),
    "tool_calls_details a string": (
        lambda u: u.__setitem__("tool_calls_details", "search_web"),
        {},
    ),
    "tool entry invocation a string": (
        lambda u: u["tool_calls_details"]["search_web"].__setitem__("invocation", "1"),
        {},
    ),
    "cost a list": (lambda u: u.__setitem__("cost", [1]), ALL_COSTS),
    "one breakdown cost negative": (
        lambda u: u["cost"].__setitem__("output_cost", -1),
        {"output_cost_nano": None},
    ),
}


@pytest.mark.parametrize("name", MALFORMED)
def test_a_malformed_shape_parses_loses_only_that_figure_and_logs_once(fast, name, caplog):
    mutate, expected_changes = MALFORMED[name]
    clean = usage_from_agent_response(fast)
    mutate(fast)
    with caplog.at_level(logging.WARNING):
        caplog.clear()
        usage = usage_from_agent_response(fast)
    assert len(caplog.records) == 1
    expected = {**vars(clean), **expected_changes}
    actual = vars(usage)
    for key in (k for k in expected if k not in ("raw", "tool_calls")):
        assert actual[key] == expected[key], key
    assert usage.raw == fast  # the object is always kept as received


def test_malformed_tool_calls_become_unknown_per_figure(fast):
    fast["tool_calls_details"]["search_web"]["invocation"] = "1"
    assert usage_from_agent_response(fast).tool_calls == {
        "search_web": ToolCallUsage(None, 1_000_000)
    }
    fast["tool_calls_details"] = {"search_web": "oops", "fetch_url": {"invocation": 2}}
    assert usage_from_agent_response(fast).tool_calls == {
        "search_web": ToolCallUsage(None, None),
        "fetch_url": ToolCallUsage(2, None),
    }
    fast["tool_calls_details"] = "oops"
    assert usage_from_agent_response(fast).tool_calls == {}


def test_the_parser_is_total_even_for_a_hostile_mapping():
    class Hostile(dict):
        def get(self, *args):
            raise RuntimeError("boom")

    usage = usage_from_agent_response(Hostile(input_tokens=1))
    assert (usage.cost_nano_usd, usage.cost_source) == (0, "none")


def test_log_lines_never_carry_values(fast, caplog):
    fast["output_tokens"] = "pplx-" + "Zy9_" * 8
    with caplog.at_level(logging.WARNING):
        usage_from_agent_response(fast)
    assert "pplx-" not in caplog.text

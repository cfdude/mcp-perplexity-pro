"""Task 3.2 (py-decisions-tool): the one cost rule, ``decisions.decisions_usage``, and the
tool listing."""

import pytest
from agent_support import fixture, make_world, respond_with
from fastmcp import Client

from mcp_perplexity_pro.costed import cost_fields
from mcp_perplexity_pro.decisions import decisions_usage
from mcp_perplexity_pro.usage import format_usd

MODEL = "pplx-decider-v1.1-27b"
FLASH = "pplx-decider-flash-v1.2"


def test_347_input_and_3_output_tokens_cost_6940_nano_computed_with_total_350():
    usage = decisions_usage({"input_tokens": 347, "output_tokens": 3}, MODEL)
    assert usage.cost_nano_usd == 6940 and usage.cost_source == "computed"
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (347, 3, 350)
    assert usage.input_cost_nano == 6940 and usage.price_table
    assert format_usd(usage.cost_nano_usd) == "0.00000694"
    assert cost_fields(usage) == ("0.00000694", "computed")


def test_a_flash_model_costs_half_and_the_requests_name_decides():
    usage = decisions_usage({"input_tokens": 347, "output_tokens": 3}, FLASH)
    assert usage.cost_nano_usd == 3470 and usage.cost_source == "computed"
    assert cost_fields(usage) == ("0.00000347", "computed")
    assert decisions_usage({"input_tokens": 347}, "pplx-decider-flash-latest").cost_nano_usd == 3470


@pytest.mark.parametrize("model", ["pplx-decider-nope", "", None, 5])
def test_a_name_with_no_price_is_an_unknown_cost_never_twenty_nano(model):
    usage = decisions_usage({"input_tokens": 347, "output_tokens": 3}, model)
    assert usage.cost_source == "none" and usage.cost_nano_usd == 0
    assert (usage.input_tokens, usage.output_tokens) == (347, 3)  # the counts stay known
    assert cost_fields(usage) == (None, "none")


def test_input_only_still_costs_and_leaves_output_and_total_null():
    usage = decisions_usage({"input_tokens": 100}, MODEL)
    assert usage.cost_nano_usd == 2000 and usage.cost_source == "computed"
    assert usage.output_tokens is None and usage.total_tokens is None


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        "x",
        {"input_tokens": True},
        {"input_tokens": -1},
        {"input_tokens": 1.5},
        {"input_tokens": "5"},
    ],
)
def test_an_unreadable_input_count_is_unknown_not_zero(raw):
    usage = decisions_usage(raw, MODEL)
    assert usage.cost_source == "none" and usage.cost_nano_usd == 0
    assert cost_fields(usage) == (None, "none")


def test_the_raw_usage_object_is_kept():
    usage = decisions_usage({"input_tokens": 5, "output_tokens": 1, "extra": {"a": 1}}, MODEL)
    assert usage.raw == {"input_tokens": 5, "output_tokens": 1, "extra": {"a": 1}}


async def test_the_listing_has_schema_annotations_cost_and_honest_wording(make_settings):
    w = await make_world(make_settings, respond_with("decisions_noul.json"))
    try:
        async with Client(w.server) as client:
            tool = next(t for t in await client.list_tools() if t.name == "perplexity_decide")
    finally:
        await w.aclose()
    assert tool.output_schema and "answers" in tool.output_schema["properties"]
    ann = tool.annotations
    assert (ann.read_only_hint, ann.destructive_hint, ann.open_world_hint) == (False, False, True)
    desc = " ".join(tool.description.split())
    assert "$0.02 per million" in desc and "probabilities" in desc
    props = tool.input_schema["properties"]
    assert set(props) == {"state", "questions", "project", "model"}
    assert all(p.get("description") for p in props.values())
    assert "Images are not supported" in props["state"]["description"]
    assert fixture("decisions_noul.json")  # the fixture the listing world serves exists

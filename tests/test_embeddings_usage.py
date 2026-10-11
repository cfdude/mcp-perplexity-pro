"""Task 2.2 (py-embeddings): ``embeddings_usage``, the one cost rule of the tool."""

import json

from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.embeddings import embeddings_usage


def recorded(name):
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())["usage"]


def test_a_reported_cost_is_kept():
    usage = embeddings_usage("pplx-embed-v1-4b", recorded("embeddings_two_4b_dim256"))
    assert (usage.cost_nano_usd, usage.cost_source) == (360, "reported")


def test_no_cost_and_100_tokens_is_computed_from_the_model_price():
    raw = {"prompt_tokens": 100, "total_tokens": 100}
    small = embeddings_usage("pplx-embed-v1-0.6b", raw)
    big = embeddings_usage("pplx-embed-v1-4b", raw)
    assert (small.cost_nano_usd, small.cost_source) == (400, "computed")
    assert (big.cost_nano_usd, big.cost_source) == (3000, "computed")
    assert small.input_tokens == 100 and small.price_table and small.raw == raw


def test_a_non_usd_cost_falls_back_to_the_computed_price():
    raw = {"prompt_tokens": 10, "cost": {"currency": "EUR", "total_cost": 1.0}}
    usage = embeddings_usage("pplx-embed-v1-0.6b", raw)
    assert (usage.cost_nano_usd, usage.cost_source) == (40, "computed")


def test_an_unpriced_model_or_no_tokens_or_no_usage_is_unknown_never_zero_computed():
    raw = {"prompt_tokens": 10}
    assert embeddings_usage("pplx-embed-nope", raw).cost_source == "none"
    assert embeddings_usage(None, raw).cost_source == "none"
    assert embeddings_usage("pplx-embed-v1-0.6b", {"total_tokens": 3}).cost_source == "none"
    assert embeddings_usage("pplx-embed-v1-0.6b", None).cost_source == "none"


def test_a_reported_zero_stays_reported_zero():
    raw = {"prompt_tokens": 10, "cost": {"currency": "USD", "total_cost": 0}}
    usage = embeddings_usage("pplx-embed-v1-4b", raw)
    assert (usage.cost_nano_usd, usage.cost_source) == (0, "reported")

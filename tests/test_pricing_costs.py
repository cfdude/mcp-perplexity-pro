"""Task 2.3: computed-cost helpers (usage-recording "Cost source", "Documented prices")."""

import pytest

from mcp_perplexity_pro.pricing import (
    agent_tool_cost_nano,
    decisions_cost_nano,
    embeddings_cost_nano,
    search_cost_nano,
)
from mcp_perplexity_pro.usage import format_usd


def test_search_requests():
    assert search_cost_nano(1, "fast") == 1_000_000
    assert search_cost_nano(1, "standard") == 5_000_000
    assert format_usd(search_cost_nano(1000, "fast")) == "1"  # $1.00 per 1,000 requests
    assert format_usd(search_cost_nano(1000, "standard")) == "5"  # $5.00
    assert search_cost_nano(0, "fast") == 0


@pytest.mark.parametrize(
    ("model", "nano"),
    [
        ("pplx-embed-v1-0.6b", 4_000_000),
        ("pplx-embed-v1-4b", 30_000_000),
        ("pplx-embed-context-v1-0.6b", 8_000_000),
        ("pplx-embed-context-v1-4b", 50_000_000),
    ],
)
def test_one_million_embeddings_tokens(model, nano):
    assert embeddings_cost_nano(model, 1_000_000) == nano


def test_decisions_input_tokens():
    assert decisions_cost_nano(1_000_000) == 20_000_000
    assert decisions_cost_nano(0) == 0


def test_agent_tools():
    assert agent_tool_cost_nano("web_search", 1) == 2_500_000
    assert agent_tool_cost_nano("web_search", 1, search_type="fast") == 1_000_000
    assert agent_tool_cost_nano("fetch_url", 4) == 2_000_000
    assert agent_tool_cost_nano("sandbox", 2) == 60_000_000  # per session


def test_the_observed_search_web_alias_agrees_with_web_search():
    assert agent_tool_cost_nano("search_web", 3) == agent_tool_cost_nano("web_search", 3)
    fast = agent_tool_cost_nano("search_web", 1, search_type="fast")
    assert fast == agent_tool_cost_nano("web_search", 1, search_type="fast") == 1_000_000


def test_zero_tokens_cost_nothing():
    assert embeddings_cost_nano("pplx-embed-v1-4b", 0) == 0
    assert agent_tool_cost_nano("fetch_url", 0) == 0


@pytest.mark.parametrize(
    "call",
    [
        lambda: embeddings_cost_nano("pplx-embed-v9", 10),
        lambda: search_cost_nano(1, "deep"),
        lambda: agent_tool_cost_nano("teleport", 1),
        lambda: agent_tool_cost_nano("web_search", 1, search_type="deep"),
        lambda: search_cost_nano(-1, "fast"),
        lambda: search_cost_nano(True, "fast"),
        lambda: search_cost_nano("1", "fast"),
        lambda: search_cost_nano(1.5, "fast"),
        lambda: embeddings_cost_nano("pplx-embed-v1-4b", -5),
        lambda: embeddings_cost_nano(None, 5),
        lambda: decisions_cost_nano(None),
        lambda: decisions_cost_nano(-1),
        lambda: agent_tool_cost_nano(["web_search"], 1),
        lambda: agent_tool_cost_nano("fetch_url", False),
        lambda: embeddings_cost_nano(["pplx-embed-v1-4b"], 1),  # unhashable
        lambda: search_cost_nano(1, {}),  # unhashable
        lambda: agent_tool_cost_nano("web_search", 1, search_type=["fast"]),  # unhashable
    ],
)
def test_unknown_or_malformed_inputs_give_none_never_raise(call):
    assert call() is None

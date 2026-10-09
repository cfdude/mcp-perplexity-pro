"""Task 2.2: the pricing constants equal the recorded copy of the documented pricing page
(usage-recording "Documented prices"; design D4). The live re-check is in
``test_pricing_live.py`` (marker ``live``)."""

import json

from fixture_support import FIXTURE_DIR
from pricing_page import PAGE_URL, parse_prices

from mcp_perplexity_pro import pricing

EXCERPT = json.loads((FIXTURE_DIR / "pricing_page.json").read_text())
SIDECAR = json.loads((FIXTURE_DIR / "pricing_page.meta.json").read_text())


def constant_prices() -> dict[str, int]:
    """The constants of ``pricing.py`` in the key space ``parse_prices`` produces."""
    prices = {f"agent.{tool}": nano for tool, nano in pricing.AGENT_TOOL_NANO.items()}
    prices["agent.web_search_fast"] = pricing.AGENT_WEB_SEARCH_FAST_NANO
    prices["agent.sandbox_search"] = pricing.AGENT_SANDBOX_SEARCH_NANO
    prices.update(
        {f"search.{kind}": nano for kind, nano in pricing.SEARCH_NANO_PER_REQUEST.items()}
    )
    prices.update({f"embeddings.{m}": n for m, n in pricing.EMBEDDINGS_NANO_PER_TOKEN.items()})
    prices.update({f"decisions.{m}": n for m, n in pricing.DECISIONS_NANO_PER_INPUT_TOKEN.items()})
    return prices


def differences(documented: dict[str, int], constants: dict[str, int]) -> list[str]:
    return [
        f"{key}: documented {documented.get(key)}, constant {constants.get(key)}"
        for key in sorted(documented.keys() | constants.keys())
        if documented.get(key) != constants.get(key)
    ]


def test_every_constant_equals_the_recorded_documented_price():
    documented = parse_prices(EXCERPT["tables"])
    assert len(documented) == 16  # the page's sixteen prices, so a dropped row cannot pass
    assert differences(documented, constant_prices()) == []


def test_the_comparison_fails_when_a_constant_is_changed_by_hand(monkeypatch):
    monkeypatch.setitem(pricing.SEARCH_NANO_PER_REQUEST, "fast", 1_000_001)
    documented = parse_prices(EXCERPT["tables"])
    assert differences(documented, constant_prices()) == [
        "search.fast: documented 1000000, constant 1000001"
    ]


def test_the_table_date_and_source_match_the_recorded_capture():
    assert pricing.PRICES_AS_OF == SIDECAR["capture_date"] == "2026-10-09"
    assert pricing.PRICES_SOURCE == PAGE_URL == EXCERPT["source"]


def test_the_observed_search_web_key_is_an_alias_of_web_search():
    assert pricing.AGENT_TOOL_ALIASES == {"search_web": "web_search"}
    assert all(target in pricing.AGENT_TOOL_NANO for target in pricing.AGENT_TOOL_ALIASES.values())

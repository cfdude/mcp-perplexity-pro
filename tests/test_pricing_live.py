"""Task 2.2: re-fetch the documented pricing page and compare it with the constants.

Deselected by default (``-m 'not live'``) and not part of CI. Run deliberately::

    uv run pytest -m live tests/test_pricing_live.py

It needs the network but no API key (the page is public documentation).
"""

import json

import httpx2
import pytest
from fixture_support import FIXTURE_DIR
from pricing_page import PAGE_URL, decisions_alias_map, extract_notes, extract_tables, parse_prices
from test_pricing import constant_prices, differences

from mcp_perplexity_pro.pricing import DECISIONS_PRICED_AS

pytestmark = [pytest.mark.live, pytest.mark.allow_network]


async def test_live_pricing_page_matches_the_constants_and_the_recorded_excerpt():
    async with httpx2.AsyncClient(follow_redirects=True, timeout=30) as http:
        response = await http.get(PAGE_URL)
    response.raise_for_status()
    live = parse_prices(extract_tables(response.text))
    recorded = parse_prices(json.loads((FIXTURE_DIR / "pricing_page.json").read_text())["tables"])
    assert differences(live, constant_prices()) == []
    assert differences(live, recorded) == []
    # the notes that say which names bill as which row (design D3)
    assert decisions_alias_map(extract_notes(response.text)) == DECISIONS_PRICED_AS

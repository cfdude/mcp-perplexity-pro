"""Live smoke test: authenticated GET /v1/models against the real API.

Deselected by default (``-m 'not live'``). Run deliberately with a real key in the
environment, never stored in the repo::

    PERPLEXITY_API_KEY=... uv run pytest -m live tests/test_client_live.py
"""

import os

import pytest

from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.settings import load_settings

pytestmark = [pytest.mark.live, pytest.mark.allow_network]


async def test_live_list_models():
    if not os.environ.get("PERPLEXITY_API_KEY"):
        pytest.skip("PERPLEXITY_API_KEY is not set")
    client = PerplexityClient(load_settings())
    try:
        result = await client.list_models()
    finally:
        await client.aclose()
    assert result.data, "the live catalog returned no models"
    assert all("/" in m.id for m in result.data)
    assert all(m.owned_by for m in result.data)
    assert any(m.pricing and m.pricing.input is not None for m in result.data)

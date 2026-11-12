"""Drift of the packaged routing evidence against the matrix (routing-v2 task 2.4).

The offline test fails when a shortlist id or the fallback model is not a key of the packaged
matrix baseline (``matrix.load_baseline``); the ``live`` test fails when one is not listed by
``GET /v1/models`` now. Run the live one with ``PERPLEXITY_API_KEY=... uv run pytest -m live
tests/test_routing_evidence.py``.
"""

import os

import pytest

from mcp_perplexity_pro import matrix
from mcp_perplexity_pro import routing_evidence as ev
from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.settings import load_settings


def routed_ids(evidence: ev.Evidence) -> set[str]:
    return {*evidence.shortlist, evidence.fallbacks["default"].model}


def test_every_shortlist_id_and_the_fallback_model_is_in_the_packaged_matrix_baseline():
    baseline = matrix.load_baseline()
    missing = sorted(routed_ids(ev.load_packaged()) - set(baseline.models))
    assert not missing, f"not in model_matrix_baseline.json: {missing}"


def test_every_routed_model_is_available_and_priced_in_the_baseline():
    baseline = matrix.load_baseline()
    for model_id in sorted(routed_ids(ev.load_packaged())):
        row = baseline.models[model_id]
        assert row.status == "available", model_id
        assert row.pricing.input is not None and row.pricing.output is not None, model_id


@pytest.mark.live
@pytest.mark.allow_network
async def test_every_shortlist_id_and_the_fallback_model_is_in_the_live_catalog():
    if not os.environ.get("PERPLEXITY_API_KEY"):
        pytest.skip("PERPLEXITY_API_KEY is not set")
    client = PerplexityClient(load_settings())
    try:
        listed = {m.id for m in (await client.list_models()).data}
    finally:
        await client.aclose()
    missing = sorted(routed_ids(ev.load_packaged()) - listed)
    assert not missing, f"not listed by GET /v1/models: {missing}"

"""Documented Perplexity prices, in integer nano-USD (10^-9 USD), for costs the API does not report.

Verified 2026-10-09 against ``PRICES_SOURCE`` (design D4). A computed cost is only ever a
fallback for a response that carries no cost of its own, and every event it prices stores
``PRICES_AS_OF`` so a later price change cannot silently reinterpret old rows. A test pins every
constant to a recorded copy of the page's tables (``tests/fixtures/pricing_page.json``), and a
``live``-marked test re-fetches the page.

Unit of each price: per request (Search), per token (Embeddings, Decisions input), per
invocation (Agent tools) or per session (Agent ``sandbox``). Agent token prices are not here:
the Agent response reports its own cost.
"""

PRICES_AS_OF = "2026-10-09"
PRICES_SOURCE = "https://docs.perplexity.ai/docs/getting-started/pricing.md"

# Search API: $5.00 per 1,000 requests standard, $1.00 with ``search_type: "fast"``.
SEARCH_NANO_PER_REQUEST = {"standard": 5_000_000, "fast": 1_000_000}

# Embeddings: $0.004 / $0.03 per 1M tokens standard, $0.008 / $0.05 contextualized.
EMBEDDINGS_NANO_PER_TOKEN = {
    "pplx-embed-v1-0.6b": 4,
    "pplx-embed-v1-4b": 30,
    "pplx-embed-context-v1-0.6b": 8,
    "pplx-embed-context-v1-4b": 50,
}

# Decisions: $0.02 per 1M input tokens, output free, no per-request fee.
DECISIONS_NANO_PER_INPUT_TOKEN = {"pplx-decider-v1.1-27b": 20, "pplx-decider-v1-27b": 20}

# Agent tools, keyed by their documented name. ``web_search`` here is the standard price; the
# Fast Search price is ``AGENT_WEB_SEARCH_FAST_NANO``. ``sandbox`` is per session (a 20-minute
# billing window); searches made from inside it cost ``AGENT_SANDBOX_SEARCH_NANO`` each.
AGENT_TOOL_NANO = {
    "web_search": 2_500_000,
    "image_search": 2_500_000,
    "fetch_url": 500_000,
    "people_search": 5_000_000,
    "finance_search": 5_000_000,
    "sandbox": 30_000_000,
}
AGENT_WEB_SEARCH_FAST_NANO = 1_000_000
AGENT_SANDBOX_SEARCH_NANO = 2_500_000

# The key under which ``usage.tool_calls_details`` reports an upstream tool can differ from the
# documented name. Only ``search_web`` has been observed (for ``web_search``, Fast Search
# preset); any other alias is for ``py-agent-api`` to confirm against a live run.
AGENT_TOOL_ALIASES = {"search_web": "web_search"}

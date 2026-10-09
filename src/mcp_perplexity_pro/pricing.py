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


# --- Cost helpers ---------------------------------------------------------------------------
# Each returns exact integer nano-USD, or ``None`` for an unknown model, tool or search type and
# for a count that is not a non-negative int, so a caller can fall back to "cost unknown".
# They never raise. The per-cost cap (``usage.MAX_COST_NANO``) is applied by ``computed_usage``.


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _lookup(table: dict[str, int], key: object) -> int | None:
    return table.get(key) if isinstance(key, str) else None  # an unhashable key must not raise


def _times(price: int | None, count: object) -> int | None:
    n = _count(count)
    return None if price is None or n is None else price * n


def search_cost_nano(requests: int, search_type: str) -> int | None:
    """Search API: one billing unit per successful request; ``search_type`` is ``"standard"``
    or ``"fast"``."""
    return _times(_lookup(SEARCH_NANO_PER_REQUEST, search_type), requests)


def embeddings_cost_nano(model: str, tokens: int) -> int | None:
    return _times(_lookup(EMBEDDINGS_NANO_PER_TOKEN, model), tokens)


def decisions_cost_nano(input_tokens: int) -> int | None:
    """Decisions: input tokens only (output is free, there is no per-request fee); both
    documented models cost the same."""
    return _times(DECISIONS_NANO_PER_INPUT_TOKEN["pplx-decider-v1.1-27b"], input_tokens)


def agent_tool_cost_nano(
    tool: str, invocations: int, *, search_type: str | None = None
) -> int | None:
    """An Agent upstream tool: ``invocations`` calls (``sandbox``: sessions) of ``tool``.

    ``tool`` may be the documented name or an observed alias (``search_web``). The response key
    does not say whether a web search was standard or Fast Search, so ``search_type="fast"``
    selects the Fast Search price; any other value but ``None``/``"standard"`` is unknown.
    """
    name = _lookup(AGENT_TOOL_ALIASES, tool) or tool
    price = _lookup(AGENT_TOOL_NANO, name)
    if name == "web_search" and search_type not in (None, "standard"):
        price = AGENT_WEB_SEARCH_FAST_NANO if search_type == "fast" else None
    return _times(price, invocations)

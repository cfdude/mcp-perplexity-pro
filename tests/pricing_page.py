"""Read the tables of Perplexity's pricing page (markdown) into nano-USD prices.

The page is the reference for ``pricing.py`` (design D4). ``extract_tables`` pulls the five
tables the constants come from out of the page text, ``parse_prices`` turns their rows into a
flat ``{key: nano-USD}`` dict, and the recorded excerpt (``fixtures/pricing_page.json``) and
the live page both go through the same two functions, so a difference in either is a
difference in prices and never in wording.
"""

import re
from decimal import Decimal

PAGE_URL = "https://docs.perplexity.ai/docs/getting-started/pricing.md"

# heading text -> excerpt key
HEADINGS = {
    "Tool Pricing": "agent_tools",
    "Search API Pricing": "search",
    "Standard Embeddings": "embeddings_standard",
    "Contextualized Embeddings": "embeddings_contextualized",
    "Decisions API Pricing": "decisions",
}

_DOLLARS = re.compile(r"\\?\$([0-9]+(?:\.[0-9]+)?)")
_CODE = re.compile(r"`([^`]+)`")
_NANO = Decimal(10**9)


def extract_tables(markdown: str) -> dict[str, list[str]]:
    """The table rows (lines starting with ``|``) under each heading in ``HEADINGS``."""
    tables: dict[str, list[str]] = {}
    current = None
    for line in markdown.splitlines():
        if line.startswith("#"):
            current = HEADINGS.get(line.lstrip("#").strip())
            if current:
                tables.setdefault(current, [])
        elif current and line.startswith("|"):
            tables[current].append(line)
    return tables


def _cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _nano(dollars: str, unit: Decimal) -> int:
    """``dollars`` per ``unit`` of the billed thing, as nano-USD per single unit (exact)."""
    value = Decimal(dollars) * _NANO / unit
    if value != value.to_integral_value():
        raise ValueError(f"{dollars} per {unit} is not a whole number of nano-USD")
    return int(value)


def _first_price(cell: str) -> str:
    match = _DOLLARS.search(cell)
    if match is None:
        raise ValueError(f"no price in {cell!r}")
    return match.group(1)


def _data_rows(rows: list[str]) -> list[list[str]]:
    return [_cells(r) for r in rows[2:]]  # skip the header and the separator row


def parse_prices(tables: dict[str, list[str]]) -> dict[str, int]:
    prices: dict[str, int] = {}
    for name, price, description, *_ in _data_rows(tables["agent_tools"]):
        tool = _CODE.search(name).group(1)
        key = f"agent.{tool}"
        if tool == "web_search" and "Fast Search" in name:
            key = "agent.web_search_fast"
        prices[key] = _nano(_first_price(price), Decimal(1))
        sandbox_search = re.search(r"billed at \\?\$([0-9.]+) per request", description)
        if tool == "sandbox" and sandbox_search:
            prices["agent.sandbox_search"] = _nano(sandbox_search.group(1), Decimal(1))
    for name, price, *_ in _data_rows(tables["search"]):  # per 1,000 requests
        key = "search.fast" if "Fast Search" in name else "search.standard"
        prices[key] = _nano(_first_price(price), Decimal(1000))
    for table in ("embeddings_standard", "embeddings_contextualized"):  # per 1M tokens
        for name, _dimensions, price in _data_rows(tables[table]):
            prices[f"embeddings.{_CODE.search(name).group(1)}"] = _nano(
                _first_price(price), Decimal(10**6)
            )
    for name, price, *_ in _data_rows(tables["decisions"]):  # per 1M input tokens
        prices[f"decisions.{_CODE.search(name).group(1)}"] = _nano(
            _first_price(price), Decimal(10**6)
        )
    return prices

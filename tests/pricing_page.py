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
    """The FIRST table (a run of lines starting with ``|``) under each heading in ``HEADINGS``.

    A later table under the same heading (the page grew a "Billing units" table under the Search
    API heading on 2026-10-29) is not price data and is ignored; a heading with no table maps to
    an empty list, which ``parse_prices`` refuses (design D4)."""
    tables: dict[str, list[str]] = {}
    current = None
    state = "before"  # before the first table, inside it, or past it
    for line in markdown.splitlines():
        if line.startswith("#"):
            current = HEADINGS.get(line.lstrip("#").strip())
            state = "before"
            if current:
                tables.setdefault(current, [])
        elif current and line.startswith("|"):
            if state != "past":
                tables[current].append(line)
                state = "inside"
        elif state == "inside":
            state = "past"
    return tables


def extract_notes(markdown: str, heading: str = "Decisions API Pricing") -> list[str]:
    """The non-empty note lines (starting with ``>``) under ``heading``, verbatim."""
    notes: list[str] = []
    inside = False
    for line in markdown.splitlines():
        if line.startswith("#"):
            inside = line.lstrip("#").strip() == heading
        elif inside and line.startswith(">") and line.lstrip("> ").strip():
            notes.append(line)
    return notes


def decisions_alias_map(notes: list[str]) -> dict[str, str]:
    """Every model name the Decisions notes say selects another model (``A`` and ``B`` select
    ``C``), as ``{A: C, B: C}``. A name that is itself a priced row is never a key."""
    aliases: dict[str, str] = {}
    for sentence in re.split(r"(?<=\.)\s+", " ".join(n.lstrip("> ") for n in notes)):
        if " select " not in sentence:
            continue
        left, right = sentence.split(" select ", 1)
        target = _CODE.search(right)
        if target is None:
            continue
        for name in _CODE.findall(left):
            aliases[name] = target.group(1)
    return aliases


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


# The prices ``pricing.py`` is built from. A page that loses one of these rows is a failure of
# the parser, not a smaller set of prices.
REQUIRED = (
    "agent.web_search",
    "agent.web_search_fast",
    "agent.fetch_url",
    "search.standard",
    "search.fast",
    "embeddings.pplx-embed-v1-0.6b",
    "embeddings.pplx-embed-v1-4b",
    "embeddings.pplx-embed-context-v1-0.6b",
    "embeddings.pplx-embed-context-v1-4b",
    "decisions.pplx-decider-v1.2",
    "decisions.pplx-decider-flash-v1.2",
)


def parse_prices(tables: dict[str, list[str]]) -> dict[str, int]:
    for name in HEADINGS.values():
        if len(tables.get(name, [])) < 3:  # a header, a separator and at least one row
            raise ValueError(f"no price table under the {name!r} heading")
    prices = _parse_rows(tables)
    missing = [key for key in REQUIRED if key not in prices]
    if missing:
        raise ValueError(f"the page has no price row for {', '.join(missing)}")
    return prices


def _parse_rows(tables: dict[str, list[str]]) -> dict[str, int]:
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

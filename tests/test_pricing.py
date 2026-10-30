"""Task 2.2: the pricing constants equal the recorded copy of the documented pricing page
(usage-recording "Documented prices"; design D4). The live re-check is in
``test_pricing_live.py`` (marker ``live``)."""

import json

import pytest
from fixture_support import FIXTURE_DIR
from pricing_page import (
    HEADINGS,
    PAGE_URL,
    decisions_alias_map,
    extract_tables,
    parse_prices,
)

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
    # the page's own rows only; the other accepted names are ``DECISIONS_PRICED_AS``
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
    assert pricing.PRICES_AS_OF == SIDECAR["capture_date"] == "2026-10-29"
    assert pricing.PRICES_SOURCE == PAGE_URL == EXCERPT["source"]


def test_the_observed_search_web_key_is_an_alias_of_web_search():
    assert pricing.AGENT_TOOL_ALIASES == {"search_web": "web_search"}
    assert all(target in pricing.AGENT_TOOL_NANO for target in pricing.AGENT_TOOL_ALIASES.values())


# --- the Decisions rows and the names that bill as one of them (design D3) ------------------------


def test_the_decisions_constants_are_exactly_the_pages_two_rows():
    assert pricing.DECISIONS_NANO_PER_INPUT_TOKEN == {
        "pplx-decider-v1.2": 20,
        "pplx-decider-flash-v1.2": 10,
    }
    page = {k for k in parse_prices(EXCERPT["tables"]) if k.startswith("decisions.")}
    assert page == {f"decisions.{m}" for m in pricing.DECISIONS_NANO_PER_INPUT_TOKEN}


def test_every_priced_as_target_is_a_page_row_and_no_alias_is_a_row_itself():
    rows = set(pricing.DECISIONS_NANO_PER_INPUT_TOKEN)
    assert set(pricing.DECISIONS_PRICED_AS.values()) <= rows
    assert not set(pricing.DECISIONS_PRICED_AS) & rows


def test_the_pages_notes_say_what_the_priced_as_map_says():
    notes = EXCERPT["notes"]["decisions"]
    assert decisions_alias_map(notes) == pricing.DECISIONS_PRICED_AS


def test_the_alias_reader_reads_each_sentence_of_the_note():
    notes = ["> **Aliases:** `a` and `b/a` select `row-1`. `c` selects `row-2`. Requests that "]
    notes[0] += "name `d` or `e` select `row-1` and bill at \\$0.02."
    assert decisions_alias_map(notes) == {
        "a": "row-1",
        "b/a": "row-1",
        "d": "row-1",
        "e": "row-1",
    }  # "`c` selects" is not the page's "select" form and is not read


# --- the parser (design D4) ----------------------------------------------------------------------

EXTRA_TABLE_PAGE = """\
## Search API Pricing

| API | Price per 1K requests | Description |
| - | :-: | - |
| **Search API** | \\$5.00 | Raw |
| **Search API with Fast** | \\$1.00 | Fast |

> [!NOTE]
> Billing unit.

| Request | Billing units | Cost |
| - | :-: | -: |
| One `POST /search` | 1 | \\$5.00 |
"""


def test_the_parser_keeps_the_first_table_under_a_heading_and_ignores_a_later_one():
    tables = extract_tables(EXTRA_TABLE_PAGE)
    assert [row.split("|")[1].strip() for row in tables["search"][2:]] == [
        "**Search API**",
        "**Search API with Fast**",
    ]
    assert len(tables["search"]) == 4


def test_the_recorded_page_still_parses_to_sixteen_prices_with_an_extra_table_appended():
    # rebuild a full page from the recorded tables, then append a second table under Search
    sections = []
    for heading, key in HEADINGS.items():
        rows = "\n".join(EXCERPT["tables"][key])
        extra = "\n\n" + EXTRA_TABLE_PAGE.split("\n\n", 1)[1] if key == "search" else ""
        sections.append(f"## {heading}\n\n{rows}{extra}\n")
    page = "\n".join(sections)
    tables = extract_tables(page)
    assert tables == EXCERPT["tables"]
    assert len(parse_prices(tables)) == 16


def test_a_missing_needed_price_row_fails_the_parse():
    tables = {k: list(v) for k, v in EXCERPT["tables"].items()}
    tables["decisions"] = [row for row in tables["decisions"] if "flash" not in row]
    with pytest.raises(ValueError, match="pplx-decider-flash-v1.2"):
        parse_prices(tables)


def test_a_malformed_row_still_raises():
    tables = {k: list(v) for k, v in EXCERPT["tables"].items()}
    tables["search"][2] = "| **Search API** | free | Raw |"
    with pytest.raises(ValueError, match="no price"):
        parse_prices(tables)


@pytest.mark.parametrize("heading", sorted(set(HEADINGS.values())))
def test_a_heading_with_no_table_fails_the_parse(heading):
    tables = {k: list(v) for k, v in EXCERPT["tables"].items()}
    tables[heading] = []
    with pytest.raises(ValueError, match=heading):
        parse_prices(tables)

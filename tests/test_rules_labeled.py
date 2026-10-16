"""routing-rules-v1 task 1.1: the labeled prompt set is the contract of the rules classifier.

The set was written before the rules. Changing a rule means changing the set first: every
``clear`` prompt must classify to its expected tier, every ``borderline`` one within one tier.
"""

import json
from collections import Counter

import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.rules import classify

PROMPTS = json.loads((FIXTURE_DIR / "routing_prompts.json").read_text())
TIERS = ("light", "standard", "complex")
RANK = {tier: n for n, tier in enumerate(TIERS)}
# A single-signal prompt triggers exactly one rule; numbered items count as questions.
SIGNALS_OF = {
    "vocabulary": ("vocabulary",),
    "length": ("length",),
    "questions": ("questions",),
    "numbered_items": ("questions",),
    "lookup": ("lookup",),
}


def label(item):
    return f"{item['mark']}-{item['expected']}-{item['text'][:40]!r}"


def test_the_set_is_big_enough_and_covers_every_tier():
    assert len(PROMPTS) >= 40
    counts = Counter(p["expected"] for p in PROMPTS)
    assert all(counts[tier] >= 10 for tier in TIERS), counts
    assert {p["mark"] for p in PROMPTS} == {"clear", "borderline"}
    assert all(p["expected"] in TIERS for p in PROMPTS)


def test_every_rule_has_a_clear_single_signal_prompt():
    singles = {p["single_signal"] for p in PROMPTS if p["mark"] == "clear" and "single_signal" in p}
    assert singles == set(SIGNALS_OF)


@pytest.mark.parametrize("item", [p for p in PROMPTS if p["mark"] == "clear"], ids=label)
def test_a_clear_prompt_classifies_to_its_expected_tier(item):
    assert classify(item["text"]).tier == item["expected"]


@pytest.mark.parametrize("item", [p for p in PROMPTS if p["mark"] == "borderline"], ids=label)
def test_a_borderline_prompt_lands_within_one_tier(item):
    assert abs(RANK[classify(item["text"]).tier] - RANK[item["expected"]]) <= 1


@pytest.mark.parametrize("item", [p for p in PROMPTS if "single_signal" in p], ids=label)
def test_a_single_signal_prompt_fires_only_its_own_signal(item):
    assert classify(item["text"]).signals == SIGNALS_OF[item["single_signal"]]

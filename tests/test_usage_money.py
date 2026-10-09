"""Task 2.1: money as integer nano-USD (usage-recording "Exact money"; design D2)."""

import math
from decimal import Decimal

import pytest

from mcp_perplexity_pro.usage import (
    MAX_COST_NANO,
    MAX_TOKENS,
    format_usd,
    to_nano,
    to_tokens,
)


@pytest.mark.parametrize(
    ("value", "nano"),
    [
        (0.00021, 210_000),
        (0.00125, 1_250_000),
        (0.0000000005, 1),  # half-up boundary: 0.5 nano rounds to 1
        (0.0000000004, 0),
        (1.5e-9, 2),  # 1.5 nano: exact only through the JSON text (the binary float is below)
        (3.5e-9, 4),
        (0.1 + 0.2, 300_000_000),  # repr noise (0.30000000000000004) is absorbed
        (0, 0),
        (0.0, 0),
        (1, 1_000_000_000),
        (1e3, MAX_COST_NANO),  # exactly 1,000 USD is accepted
    ],
)
def test_to_nano_converts_through_the_json_text(value, nano):
    assert to_nano(value) == nano


def test_ten_small_costs_sum_exactly():
    assert sum(to_nano(0.00021) for _ in range(10)) == 2_100_000


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        -0.1,
        -1,
        "1",
        None,
        [1],
        Decimal("1"),
        1e30,
        9.3e9,  # 9.3e18 nano: over the signed 64-bit range
        1000.000001,  # just above the cap
        1000.0000000005,  # rounds to cap + 1 nano: only the final cap check refuses it
    ],
)
def test_unusable_values_are_none_and_never_raise(value):
    assert to_nano(value) is None


def test_an_integer_whose_repr_raises_is_unusable_not_an_escape():
    huge = 10**5000  # repr() raises ValueError on CPython's int-to-str digit limit
    with pytest.raises(ValueError):
        repr(huge)
    assert to_nano(huge) is None
    assert to_tokens(huge) is None


def test_the_cap_keeps_a_thousand_capped_costs_inside_64_bits():
    assert 1000 * MAX_COST_NANO < 2**63
    assert MAX_COST_NANO == 10**12


@pytest.mark.parametrize("value", [0, 1, 3456, MAX_TOKENS])
def test_token_counts_accept_plain_non_negative_ints(value):
    assert to_tokens(value) == value


@pytest.mark.parametrize("value", [True, False, -1, "30", 30.0, None, MAX_TOKENS + 1, math.nan])
def test_token_counts_reject_everything_else(value):
    assert to_tokens(value) is None


@pytest.mark.parametrize(
    ("nano", "text"),
    [
        (1_230_000, "0.00123"),
        (0, "0"),
        (1, "0.000000001"),
        (2**63 - 1, "9223372036.854775807"),
        (1_000_000_000, "1"),
        (1_500_000_000, "1.5"),
        (210_000, "0.00021"),
    ],
)
def test_format_usd_is_exact_and_trimmed(nano, text):
    assert format_usd(nano) == text

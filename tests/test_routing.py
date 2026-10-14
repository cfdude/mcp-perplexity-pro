"""routing.resolve and routing.instructions_text (routing-modes-config, task 1.2)."""

import itertools

import pytest

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.routing import Route, instructions_text, resolve

TIERS = {"tier_light": "x/light", "tier_standard": "x/standard", "tier_complex": "x/complex"}


@pytest.fixture
def standard(make_settings):
    return make_settings()


@pytest.fixture
def custom(make_settings):
    return make_settings(routing="custom", **TIERS)


def refused(settings, **selectors):
    with pytest.raises(PerplexityError) as info:
        resolve(settings, **selectors)
    assert info.value.category == "invalid_request"
    return str(info.value)


def test_default_in_standard_mode_is_the_configured_model(standard, make_settings):
    assert resolve(standard) == Route("standard", None, "perplexity/sonar", None, "default")
    other = make_settings(model="anthropic/claude-sonnet-5-5")
    assert resolve(other).model == "anthropic/claude-sonnet-5-5"


def test_default_in_custom_mode_is_the_standard_tier(custom):
    assert resolve(custom) == Route("custom", "standard", "x/standard", None, "default")


@pytest.mark.parametrize("tier", ["light", "standard", "complex"])
def test_tier_selects_its_model_in_custom_mode(custom, tier):
    assert resolve(custom, tier=tier) == Route("custom", tier, f"x/{tier}", None, "tier")


def test_depth_selects_a_preset_in_every_mode(standard, custom):
    for settings in (standard, custom):
        route = resolve(settings, depth="medium")
        assert (route.preset, route.model, route.tier, route.selected_by) == (
            "medium",
            None,
            None,
            "depth",
        )


@pytest.mark.parametrize("model", ["anthropic/claude-opus-5-5", "not/in-the-catalog", "x/light"])
def test_an_explicit_model_is_used_verbatim_in_every_mode(standard, custom, model):
    for settings in (standard, custom):
        route = resolve(settings, model=model)
        assert (route.model, route.preset, route.tier, route.selected_by) == (
            model,
            None,
            None,
            "model",
        )


@pytest.mark.parametrize(
    "pair", list(itertools.combinations(["depth", "tier", "model"], 2)), ids="-".join
)
def test_any_two_selectors_are_refused_with_a_message_that_teaches(custom, pair):
    values = {"depth": "low", "tier": "light", "model": "x/y"}
    text = refused(custom, **{name: values[name] for name in pair})
    assert all(name in text for name in pair)
    assert "each" in text and "model" in text  # says each one picks the model
    assert "one" in text and "neither" in text  # says what to do


def test_all_three_selectors_name_all_three(custom):
    text = refused(custom, depth="low", tier="light", model="x/y")
    assert "depth" in text and "tier" in text and "model" in text


def test_tier_outside_custom_mode_names_tier_and_the_mode(standard):
    text = refused(standard, tier="light")
    assert "tier" in text and "standard" in text and "custom" in text


def test_unknown_tier_names_tier_and_the_choices(custom):
    text = refused(custom, tier="huge")
    assert "tier" in text and "light" in text and "complex" in text


@pytest.mark.parametrize("depth", ["high", "xhigh"])
def test_long_depths_point_to_research(standard, depth):
    assert "perplexity_research" in refused(standard, depth=depth)


def test_unknown_depth_names_the_choices(standard):
    text = refused(standard, depth="turbo")
    assert "depth" in text and "fast" in text and "medium" in text


def test_refusal_order_conflict_then_tier_mode_then_tier_value_then_depth(standard, custom):
    # standard mode: tier outside custom AND a depth together: the conflict message wins
    text = refused(standard, tier="light", depth="low")
    assert "cannot be combined" in text
    # tier outside custom beats an unknown tier value
    assert "custom" in refused(standard, tier="huge")
    # an unknown tier beats nothing else here, a long depth alone is its own refusal
    assert "perplexity_research" in refused(custom, depth="high")
    # a conflict beats a long depth
    assert "cannot be combined" in refused(custom, depth="high", model="x/y")


def test_resolve_is_pure_and_never_mutates_settings(custom):
    before = custom.model_dump()
    resolve(custom, tier="light")
    assert custom.model_dump() == before


# --- instructions text -----------------------------------------------------------------


def test_standard_instructions_name_the_mode_and_model_and_no_tiers(standard):
    text = instructions_text(standard)
    assert "standard" in text and "perplexity/sonar" in text
    assert "perplexity_research" in text and "depth" in text and "model" in text
    assert "light" not in text and "complex" not in text


def test_custom_instructions_list_the_three_tiers_and_how_to_pick(custom):
    text = instructions_text(custom)
    assert "custom" in text
    for name, model in (("light", "x/light"), ("standard", "x/standard"), ("complex", "x/complex")):
        assert name in text and model in text
    assert "tier" in text


def test_instructions_are_a_pure_function_of_settings_and_hold_no_secret(standard, custom):
    for settings in (standard, custom):
        text = instructions_text(settings)
        assert text == instructions_text(settings)
        assert settings.api_key.get_secret_value() not in text

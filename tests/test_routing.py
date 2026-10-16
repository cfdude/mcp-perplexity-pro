"""routing.resolve and routing.instructions_text (routing-modes-config, task 1.2)."""

import itertools

import pytest

from mcp_perplexity_pro import rules
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.routing import (
    LONG_DEPTHS,
    Route,
    description_sentence,
    dynamic_route,
    instructions_text,
    resolve,
    tier_of,
)
from mcp_perplexity_pro.rules import Classification

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
    assert "tier" not in text  # tier is not usable in standard mode


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


def test_instructions_point_to_help_in_every_mode(standard, custom, dynamic):
    for settings in (standard, custom, dynamic):
        assert "perplexity_help" in instructions_text(settings)


# --- dynamic mode (routing-rules-v1, task 2.1) ---------------------------------------------

LOOKUP = "What is the latest stable Python release?"
ANALYSIS = "Compare two designs and evaluate their trade-offs."
ORDINARY = "Tell me about otters"
TIER_ORDER = ("light", "standard", "complex")


@pytest.fixture
def dynamic(make_settings):
    return make_settings(routing="dynamic")


def raising_classify(text):
    raise AssertionError("the classifier must not run")


def test_dynamic_tiers_need_no_configuration(dynamic):
    assert dynamic_route(dynamic, "light") == Route("dynamic", "light", None, "fast", "classifier")
    assert dynamic_route(dynamic, "standard").model == "perplexity/sonar"
    assert dynamic_route(dynamic, "standard").preset is None
    assert dynamic_route(dynamic, "complex").preset == "medium"
    assert dynamic_route(dynamic, "complex").model is None


def test_the_standard_tier_is_the_tier_variable_else_the_model_variable(make_settings):
    assert dynamic_route(make_settings(routing="dynamic", model="x/m"), "standard").model == "x/m"
    both = make_settings(routing="dynamic", model="x/m", tier_standard="x/s")
    assert dynamic_route(both, "standard").model == "x/s"


def test_a_tier_variable_replaces_its_default_with_a_model(make_settings):
    s = make_settings(routing="dynamic", tier_light="x/l", tier_complex="anthropic/claude-opus-5-5")
    light, complex_ = dynamic_route(s, "light"), dynamic_route(s, "complex")
    assert (light.model, light.preset) == ("x/l", None)
    assert (complex_.model, complex_.preset) == ("anthropic/claude-opus-5-5", None)


def test_dynamic_route_ignores_the_custom_tier_fields_of_another_mode(make_settings):
    # tier_* are the dynamic replacements here; nothing is required
    assert dynamic_route(make_settings(routing="dynamic"), "light").preset == "fast"


def test_a_lookup_goes_light_and_an_analysis_goes_complex(dynamic):
    light = resolve(dynamic, text=LOOKUP)
    assert (light.mode, light.tier, light.preset, light.model) == ("dynamic", "light", "fast", None)
    assert (light.selected_by, light.classifier) == ("classifier", "rules")
    assert light.reason == "short lookup"
    complex_ = resolve(dynamic, text=ANALYSIS)
    assert (complex_.tier, complex_.preset, complex_.reason) == (
        "complex",
        "medium",
        "3 analysis terms",
    )
    standard = resolve(dynamic, text=ORDINARY)
    assert (standard.tier, standard.model, standard.preset) == (
        "standard",
        "perplexity/sonar",
        None,
    )


def test_a_ready_classification_is_used_and_the_rules_do_not_run(dynamic, monkeypatch):
    monkeypatch.setattr(rules, "classify", raising_classify)
    ready = Classification("complex", "decided elsewhere", "decisions", ("x",))
    route = resolve(dynamic, text=LOOKUP, classification=ready)
    assert (route.tier, route.reason, route.classifier) == (
        "complex",
        "decided elsewhere",
        "decisions",
    )
    assert route.selected_by == "classifier"


def test_no_text_is_the_standard_tier_by_default(dynamic):
    route = resolve(dynamic)
    assert route == Route("dynamic", "standard", "perplexity/sonar", None, "default")
    assert (route.reason, route.classifier) == (None, None)


def test_explicit_selectors_never_classify(dynamic, monkeypatch):
    monkeypatch.setattr(rules, "classify", raising_classify)
    assert resolve(dynamic, text=LOOKUP, depth="low") == Route(
        "dynamic", None, None, "low", "depth"
    )
    assert resolve(dynamic, text=LOOKUP, model="x/y") == Route(
        "dynamic", None, "x/y", None, "model"
    )
    tiered = resolve(dynamic, text=LOOKUP, tier="complex")
    assert (tiered.tier, tiered.preset, tiered.selected_by) == ("complex", "medium", "tier")
    assert (tiered.reason, tiered.classifier) == (None, None)
    assert resolve(dynamic, text=LOOKUP, tier="light", previous="complex").tier == "light"


def test_search_off_runs_the_standard_model_without_classifying(dynamic, monkeypatch):
    monkeypatch.setattr(rules, "classify", raising_classify)
    route = resolve(dynamic, text=LOOKUP, search=False)
    assert route == Route("dynamic", "standard", "perplexity/sonar", None, "default", "search off")
    assert route.classifier is None


def test_search_off_wins_over_the_follow_up_floor(dynamic):
    route = resolve(dynamic, text=LOOKUP, previous="complex", search=False)
    assert (route.tier, route.model, route.selected_by) == (
        "standard",
        "perplexity/sonar",
        "default",
    )
    assert route.reason == "search off"


def test_search_true_changes_nothing(dynamic):
    assert resolve(dynamic, text=LOOKUP, search=True) == resolve(dynamic, text=LOOKUP)


def test_search_off_with_a_preset_tier_is_refused_naming_tier_and_search(dynamic):
    for tier in ("light", "complex"):
        text = refused(dynamic, tier=tier, search=False)
        assert "tier" in text and "search" in text
        assert "always searches" in text and "model" in text and "standard" in text


def test_search_off_with_a_model_tier_is_allowed(make_settings):
    s = make_settings(routing="dynamic", tier_light="x/l")
    route = resolve(s, tier="light", search=False)
    assert (route.model, route.preset, route.selected_by) == ("x/l", None, "tier")
    standard = resolve(make_settings(routing="dynamic"), tier="standard", search=False)
    assert standard.model == "perplexity/sonar"


def test_search_off_with_depth_or_model_is_left_to_the_request_builder(dynamic):
    assert resolve(dynamic, depth="low", search=False).preset == "low"
    assert resolve(dynamic, model="x/y", search=False).model == "x/y"


def test_tier_is_accepted_in_dynamic_and_refused_in_standard(dynamic, standard):
    assert resolve(dynamic, tier="light").tier == "light"
    text = refused(standard, tier="light")
    assert "tier" in text and "standard" in text and "custom or dynamic" in text


def test_an_unknown_tier_in_dynamic_names_tier_and_the_choices(dynamic):
    text = refused(dynamic, tier="huge")
    assert "tier" in text and "light" in text and "complex" in text


def test_the_refusal_order_is_unchanged_in_dynamic(dynamic):
    assert "cannot be combined" in refused(dynamic, tier="light", depth="low")
    assert "cannot be combined" in refused(dynamic, depth="high", model="x/y")
    assert "perplexity_research" in refused(dynamic, depth="high")
    assert "perplexity_research" in refused(dynamic, depth="xhigh")


def test_the_conflict_message_in_dynamic_says_the_tier_is_picked_from_the_prompt(dynamic):
    text = refused(dynamic, tier="light", model="x/y")
    assert "`tier`" in text and "`model`" in text and "neither" in text
    assert "picked from the prompt" in text and "perplexity/sonar" not in text


def test_the_conflict_message_in_other_modes_keeps_naming_the_default(standard, custom):
    assert "perplexity/sonar" in refused(standard, depth="low", model="x/y")
    assert "x/standard" in refused(custom, depth="low", model="x/y")


# --- the follow-up floor --------------------------------------------------------------------


def test_a_floor_raises_a_lower_verdict_and_says_so(dynamic):
    route = resolve(dynamic, text=LOOKUP, previous="complex")
    assert (route.tier, route.preset, route.selected_by) == ("complex", "medium", "classifier")
    assert route.reason == "short lookup, held at complex"
    assert route.classifier == "rules"
    mid = resolve(dynamic, text=LOOKUP, previous="standard")
    assert (mid.tier, mid.reason) == ("standard", "short lookup, held at standard")


def test_a_floor_never_lowers_and_says_nothing_when_it_did_not_apply(dynamic):
    assert resolve(dynamic, text=ANALYSIS, previous="light").reason == "3 analysis terms"
    assert resolve(dynamic, text=ANALYSIS, previous="standard").tier == "complex"
    same = resolve(dynamic, text=ANALYSIS, previous="complex")
    assert same.tier == "complex" and "held" not in same.reason
    assert "held" not in resolve(dynamic, text=ORDINARY, previous="light").reason
    assert resolve(dynamic, text=ORDINARY, previous=None).reason == "no signals"


def test_the_final_reason_is_capped_at_120_ascii_characters(dynamic):
    long_reason = "x" * 200
    capped = resolve(
        dynamic, classification=Classification("light", long_reason), previous="complex"
    )
    assert len(capped.reason) == 120 and capped.reason.isascii()
    odd = resolve(dynamic, classification=Classification("light", "caf\u00e9 " * 40))
    assert odd.reason.isascii() and len(odd.reason) <= 120


def test_dynamic_never_selects_high_or_xhigh_for_any_tier_signal_or_floor(make_settings):
    signal_sets = [()]
    names = ("vocabulary", "length", "questions", "lookup")
    for size in range(1, len(names) + 1):
        signal_sets += list(itertools.combinations(names, size))
    settings = [
        make_settings(routing="dynamic"),
        make_settings(routing="dynamic", tier_light="x/l", tier_standard="x/s", tier_complex="x/c"),
    ]
    for s in settings:
        for tier in TIER_ORDER:
            for signals in signal_sets:
                for previous in (None, *TIER_ORDER):
                    c = Classification(tier, "r", "rules", signals)
                    for search in (None, True, False):
                        route = resolve(s, classification=c, previous=previous, search=search)
                        assert route.preset not in LONG_DEPTHS
                        assert route.preset in (None, "fast", "medium")
                    assert dynamic_route(s, tier).preset not in LONG_DEPTHS


# --- tier_of: the tier a stored turn ran ----------------------------------------------------


def test_tier_of_reads_the_stored_preset_first(dynamic):
    assert tier_of(dynamic, "fast", "perplexity/sonar") == "light"
    assert tier_of(dynamic, "medium", "perplexity/sonar") == "complex"
    assert tier_of(dynamic, "medium", None) == "complex"


def test_tier_of_matches_a_model_against_the_tiers_models(dynamic, make_settings):
    assert tier_of(dynamic, None, "perplexity/sonar") == "standard"
    s = make_settings(routing="dynamic", tier_complex="anthropic/claude-opus-5-5")
    assert tier_of(s, None, "anthropic/claude-opus-5-5") == "complex"
    assert tier_of(s, "medium", "perplexity/sonar") == "standard"  # a replaced tier has no preset


def test_a_tier_that_no_stored_value_matches_counts_as_standard(dynamic):
    assert tier_of(dynamic, None, "vendor/explicit") == "standard"
    assert tier_of(dynamic, None, None) == "standard"
    assert tier_of(dynamic, "low", "vendor/explicit") == "standard"


def test_a_tie_between_tiers_takes_the_highest(make_settings):
    s = make_settings(routing="dynamic", tier_light="x/same", tier_standard="x/same")
    assert tier_of(s, None, "x/same") == "standard"
    s = make_settings(routing="dynamic", tier_light="x/same", tier_complex="x/same")
    assert tier_of(s, None, "x/same") == "complex"
    s = make_settings(
        routing="dynamic", tier_light="x/same", tier_standard="x/same", tier_complex="x/same"
    )
    assert tier_of(s, None, "x/same") == "complex"


# --- telling the agent: dynamic instructions and description (task 4.1) ---------------------


def test_dynamic_instructions_name_the_mode_the_tiers_and_how_to_override(dynamic):
    text = instructions_text(dynamic)
    assert "Routing mode: dynamic" in text
    assert "picks a tier from the prompt" in text
    assert "light = preset fast" in text
    assert "standard = perplexity/sonar" in text and "complex = preset medium" in text
    assert "`tier`" in text and "`depth`" in text and "`model`" in text and "overrides" in text
    assert "perplexity_research" in text and "perplexity_help" in text
    assert "high" in text and "xhigh" in text


def test_dynamic_instructions_show_a_replaced_tier_as_its_model(make_settings):
    s = make_settings(routing="dynamic", tier_light="x/l", tier_standard="x/s", tier_complex="x/c")
    text = instructions_text(s)
    assert "light = x/l" in text and "standard = x/s" in text and "complex = x/c" in text
    assert "preset" not in text.split("Pass")[0]


def test_dynamic_instructions_and_description_are_pure_and_hold_no_secret(dynamic):
    for text in (instructions_text(dynamic), description_sentence(dynamic)):
        assert dynamic.api_key.get_secret_value() not in text
    assert instructions_text(dynamic) == instructions_text(dynamic)
    assert description_sentence(dynamic) == description_sentence(dynamic)


def test_the_dynamic_description_sentence_states_mode_tiers_and_override(dynamic):
    text = description_sentence(dynamic)
    assert "Routing mode: dynamic" in text and "from the prompt" in text
    assert "light runs preset fast" in text and "standard runs perplexity/sonar" in text
    assert "complex runs preset medium" in text
    assert "`tier`, `depth` or `model` overrides" in text
    assert "always used as given" in text and "perplexity_usage" in text


def test_the_other_modes_description_sentences_are_unchanged(standard, custom):
    assert "Routing mode: standard" in description_sentence(standard)
    assert "dynamic" not in description_sentence(standard)
    assert "Routing mode: custom" in description_sentence(custom)
    assert "dynamic" not in description_sentence(custom)
    assert "dynamic" not in instructions_text(standard) + instructions_text(custom)

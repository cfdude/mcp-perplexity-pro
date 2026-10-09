"""Task 2.1: ``agent.build_request`` and the pure option validation (design D2)."""

import copy
import json

import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro.agent import AskOptions, build_request
from mcp_perplexity_pro.errors import PerplexityError

MODEL = "openai/gpt-6-luna"


def sidecar_request(name):
    return json.loads((FIXTURE_DIR / f"{name}.meta.json").read_text())["request"]


def expected_from_sidecar(name, *, store):
    """Request equality, defined once: the sidecar's request plus ``store`` minus ``reasoning``,
    and ``json_schema.name`` compared with the constant ``answer`` (not the probe's)."""
    request = copy.deepcopy(sidecar_request(name))
    request.pop("reasoning", None)
    request["store"] = store
    if "response_format" in request:
        request["response_format"]["json_schema"]["name"] = "answer"
    return request


SIDECAR_CASES = {
    "agent_fast_filters": AskOptions(
        depth="fast",
        domains=["python.org"],
        recency="month",
        country="US",
        instructions="Answer tersely. Cite sources.",
        max_output_tokens=400,
    ),
    "agent_fast_deny_after": AskOptions(
        depth="fast", domains=["-reddit.com", "-wikipedia.org"], after="2026-09-15", max_results=5
    ),
    "agent_model_without_tools": AskOptions(model=MODEL, search=False),
    "agent_incomplete_truncated": AskOptions(model=MODEL, search=False, max_output_tokens=16),
    "agent_structured_output": AskOptions(
        depth="fast",
        json_schema=sidecar_request("agent_structured_output")["response_format"]["json_schema"][
            "schema"
        ],
    ),
}


@pytest.mark.parametrize("name", SIDECAR_CASES)
def test_built_request_equals_the_recorded_sidecar_request(name):
    options = SIDECAR_CASES[name]
    built = build_request(options, sidecar_request(name)["input"], store=False)
    assert built == expected_from_sidecar(name, store=False)


def test_the_structured_case_really_differs_from_the_probe_only_by_schema_name():
    probe = sidecar_request("agent_structured_output")["response_format"]["json_schema"]
    assert probe["name"] == "capital"  # the substitution in expected_from_sidecar is needed
    built = build_request(SIDECAR_CASES["agent_structured_output"], "q", store=False)[
        "response_format"
    ]
    assert built == {
        "type": "json_schema",
        "json_schema": {"name": "answer", "schema": probe["schema"]},
    }
    assert "strict" not in built and "strict" not in built["json_schema"]


def test_background_research_shape_equals_the_medium_submit_sidecar_plus_store_true():
    request = sidecar_request("agent_background_submit_medium")
    built = build_request(AskOptions(depth="medium"), request["input"], store=True, background=True)
    assert built == {**request, "store": True}


# --- shapes with NO sidecar: asserted against inline expected dicts written here ------------
# (nothing recorded backs them; they follow the design table and the documented API)


def test_inline_preset_low_without_filters_has_no_tools():  # no sidecar
    assert build_request(AskOptions(depth="low"), "q", store=False) == {
        "preset": "low",
        "input": "q",
        "store": False,
    }


def test_inline_default_depth_is_fast():  # no sidecar
    assert build_request(AskOptions(), "q", store=False)["preset"] == "fast"


def test_inline_explicit_model_with_search_has_one_web_search_tool_and_three_steps():  # no sidecar
    assert build_request(AskOptions(model=MODEL), "q", store=False) == {
        "model": MODEL,
        "input": "q",
        "store": False,
        "tools": [{"type": "web_search"}],
        "max_steps": 3,
    }


def test_inline_explicit_model_with_filters_keeps_the_filters_and_three_steps():  # no sidecar
    built = build_request(AskOptions(model=MODEL, recency="week"), "q", store=False)
    assert built["tools"] == [{"type": "web_search", "filters": {"search_recency_filter": "week"}}]
    assert built["max_steps"] == 3 and "preset" not in built


def test_inline_search_true_is_the_same_as_no_search_option():  # no sidecar
    for kwargs in ({"depth": "low"}, {"model": MODEL}):
        plain = build_request(AskOptions(**kwargs), "q", store=False)
        assert build_request(AskOptions(search=True, **kwargs), "q", store=False) == plain


def test_inline_anthropic_model_gets_the_default_cap_4096():  # no sidecar
    built = build_request(AskOptions(model="anthropic/claude-haiku-4-5"), "q", store=False)
    assert built["max_output_tokens"] == 4096


def test_inline_anthropic_explicit_cap_200_is_kept():  # no sidecar
    options = AskOptions(model="anthropic/claude-haiku-4-5", max_output_tokens=200)
    assert build_request(options, "q", store=False)["max_output_tokens"] == 200


def test_inline_a_non_anthropic_model_gets_no_default_cap():  # no sidecar
    assert "max_output_tokens" not in build_request(AskOptions(model=MODEL), "q", store=False)


def test_inline_before_date_is_converted_and_filters_sit_beside_max_results():  # no sidecar
    built = build_request(
        AskOptions(
            depth="low", before="2026-10-01", after="2026-10-01", max_results=50, country="de"
        ),
        "q",
        store=False,
    )
    assert built["tools"] == [
        {
            "type": "web_search",
            "max_results": 50,
            "filters": {
                "search_after_date_filter": "10/01/2026",
                "search_before_date_filter": "10/01/2026",
            },
            "user_location": {"country": "DE"},
        }
    ]


def test_inline_replay_list_input_and_previous_response_id_are_passed_through():  # no sidecar
    items = [{"type": "message", "role": "user", "content": "hi"}]
    built = build_request(AskOptions(), items, store=False, previous_response_id="resp_abc")
    assert built["input"] == items and built["previous_response_id"] == "resp_abc"
    assert "background" not in built


def test_the_schema_and_options_are_not_aliased_into_the_request():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    options = AskOptions(json_schema=schema, domains=["a.com"])
    built = build_request(options, "q", store=False)
    built["response_format"]["json_schema"]["schema"]["properties"]["a"]["type"] = "x"
    built["tools"][0]["filters"]["search_domain_filter"].append("b.com")
    assert schema["properties"]["a"]["type"] == "string" and options.domains == ["a.com"]


def test_max_steps_is_never_taken_from_the_caller():
    assert not hasattr(AskOptions(), "max_steps")
    assert "max_steps" not in build_request(
        AskOptions(depth="low", max_results=3), "q", store=False
    )


# --- refusals: invalid_request naming the option, before anything else ----------------------

TOO_LONG_DOMAIN = ["a" * 5 + ".com"] * 21
REFUSALS = {
    # Depth selects a preset
    "high depth": ({"depth": "high"}, "perplexity_research"),
    "xhigh depth": ({"depth": "xhigh"}, "perplexity_research"),
    "unknown depth": ({"depth": "turbo"}, "depth"),
    # Explicit model
    "depth with model": ({"depth": "low", "model": MODEL}, "depth"),
    "search false without model": ({"search": False}, "search"),
    "blank model": ({"model": "  "}, "model"),
    # Domain filters
    "mixed domains": ({"domains": ["python.org", "-reddit.com"]}, "domains"),
    "21 domains": ({"domains": TOO_LONG_DOMAIN}, "domains"),
    "empty domain": ({"domains": ["python.org", ""]}, "domains"),
    "whitespace domain": ({"domains": ["python .org"]}, "domains"),
    "bare dash domain": ({"domains": ["-"]}, "domains"),
    "domain list not strings": ({"domains": [1]}, "domains"),
    # Other search options
    "bad recency": ({"recency": "fortnight"}, "recency"),
    "us style date": ({"after": "09/15/2026"}, "after"),
    "impossible date": ({"after": "2026-13-40"}, "after"),
    "bad before": ({"before": "tomorrow"}, "before"),
    "trailing newline date": ({"before": "2026-10-01\n"}, "before"),
    "dates out of order": ({"after": "2026-10-01", "before": "2026-09-01"}, "after"),
    "country one letter": ({"country": "U"}, "country"),
    "country digits": ({"country": "U1"}, "country"),
    "country three letters": ({"country": "USA"}, "country"),
    "max_results zero": ({"max_results": 0}, "max_results"),
    "max_results 51": ({"max_results": 51}, "max_results"),
    "max_results bool": ({"max_results": True}, "max_results"),
    "recency with search false": ({"model": MODEL, "search": False, "recency": "week"}, "recency"),
    "domains with search false": (
        {"model": MODEL, "search": False, "domains": ["a.com"]},
        "domains",
    ),
    "max_results with search false": (
        {"model": MODEL, "search": False, "max_results": 3},
        "max_results",
    ),
    # Instructions and output cap bounds
    "instructions 10001": ({"instructions": "x" * 10001}, "instructions"),
    "instructions not a string": ({"instructions": 5}, "instructions"),
    "max_output_tokens 64001": ({"max_output_tokens": 64001}, "max_output_tokens"),
    "max_output_tokens 0": ({"max_output_tokens": 0}, "max_output_tokens"),
    "max_output_tokens bool": ({"max_output_tokens": True}, "max_output_tokens"),
    # Structured output
    "array root schema": ({"json_schema": {"type": "array", "items": {}}}, "json_schema"),
    "schema without type": ({"json_schema": {"properties": {}}}, "json_schema"),
    "schema not a mapping": ({"json_schema": "object"}, "json_schema"),
}


@pytest.mark.parametrize("case", REFUSALS)
def test_each_refusal_is_invalid_request_naming_the_option(case):
    kwargs, named = REFUSALS[case]
    with pytest.raises(PerplexityError) as info:
        build_request(AskOptions(**kwargs), "q", store=False)
    assert info.value.category == "invalid_request"
    assert named in str(info.value)


def test_high_and_xhigh_never_reach_a_request_through_any_option_combination():
    for depth in ("high", "xhigh"):
        for extra in ({}, {"domains": ["a.com"]}, {"max_output_tokens": 10}):
            with pytest.raises(PerplexityError):
                build_request(AskOptions(depth=depth, **extra), "q", store=False)


def test_boundaries_that_are_allowed():
    ok = AskOptions(
        depth="medium",
        domains=[f"d{i}.com" for i in range(20)],
        instructions="x" * 10000,
        max_output_tokens=64000,
        max_results=1,
        after="2026-10-01",
        before="2026-10-01",
    )
    assert build_request(ok, "q", store=False)["preset"] == "medium"


@pytest.mark.parametrize("bad", ["", "   ", None, 5, [], {}])
def test_input_must_be_a_non_blank_string_or_a_replay_list(bad):
    with pytest.raises(PerplexityError) as info:
        build_request(AskOptions(), bad, store=False)
    assert info.value.category == "invalid_request" and "input" in str(info.value)


def test_validation_makes_no_network_or_filesystem_contact(monkeypatch):
    import socket

    def boom(*args, **kwargs):
        raise AssertionError("network touched")

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    for kwargs, _ in REFUSALS.values():
        with pytest.raises(PerplexityError):
            build_request(AskOptions(**kwargs), "q", store=False)


def test_blank_instructions_are_the_same_as_none_and_instructions_pass_through_unchanged():
    assert "instructions" not in build_request(AskOptions(instructions="  "), "q", store=False)
    built = build_request(AskOptions(instructions="Answer tersely."), "q", store=False)
    assert built["instructions"] == "Answer tersely."

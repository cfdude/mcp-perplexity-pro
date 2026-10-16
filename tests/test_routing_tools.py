"""routing-modes-config task 3.1: ``tier``, the ``routing`` result field and the rendered
descriptions of ``perplexity_ask`` and ``perplexity_chat`` send, through ``build_server``."""

import pytest
from agent_support import make_world, respond_with
from chat_support import TOOL as CHAT
from chat_support import category as chat_category
from fastmcp import Client

ASK = "perplexity_ask"
TIERS = {"tier_light": "x/light", "tier_standard": "x/standard", "tier_complex": "x/complex"}
CUSTOM = {"routing": "custom", **TIERS}


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(**settings):
        w = await make_world(make_settings, respond_with("agent_fast.json"), **settings)
        made.append(w)
        return w

    yield build
    for w in made:
        await w.aclose()


async def tools_of(w):
    async with Client(w.server) as client:
        return {t.name: t for t in await client.list_tools()}


async def tool(w, name):
    return (await tools_of(w))[name]


# --- the routing object -----------------------------------------------------------------


async def test_default_ask_in_standard_mode_reports_its_routing(world):
    w = await world()
    out = (await w.call(ASK, query="q")).structured_content
    assert out["routing"] == {
        "mode": "standard",
        "tier": None,
        "model": "perplexity/sonar",
        "selected_by": "default",
        "classifier": None,
        "reason": None,
    }
    assert w.bodies()[0]["model"] == "perplexity/sonar" and "preset" not in w.bodies()[0]


async def test_default_ask_in_custom_mode_uses_the_standard_tier(world):
    w = await world(**CUSTOM)
    out = (await w.call(ASK, query="q")).structured_content
    assert out["routing"] == {
        "mode": "custom",
        "tier": "standard",
        "model": "x/standard",
        "selected_by": "default",
        "classifier": None,
        "reason": None,
    }
    assert w.bodies()[0]["model"] == "x/standard"


@pytest.mark.parametrize("tier", ["light", "standard", "complex"])
async def test_a_tier_ask_names_the_tier_model(world, tier):
    w = await world(**CUSTOM)
    out = (await w.call(ASK, query="q", tier=tier)).structured_content
    assert out["routing"]["selected_by"] == "tier" and out["routing"]["tier"] == tier
    assert w.bodies()[0]["model"] == f"x/{tier}"
    assert w.bodies()[0]["tools"] == [{"type": "web_search"}] and w.bodies()[0]["max_steps"] == 3


async def test_a_depth_ask_reports_a_preset_route(world):
    w = await world(**CUSTOM)
    out = (await w.call(ASK, query="q", depth="low")).structured_content
    assert out["routing"] == {
        "mode": "custom",
        "tier": None,
        "model": None,
        "selected_by": "depth",
        "classifier": None,
        "reason": None,
    }
    assert w.bodies()[0]["preset"] == "low"


async def test_an_explicit_model_wins_in_every_mode_and_is_sent_verbatim(world):
    for settings in ({}, CUSTOM):
        w = await world(**settings)
        out = (await w.call(ASK, query="q", model="not/in-any-catalog")).structured_content
        assert out["routing"]["selected_by"] == "model"
        assert out["routing"]["model"] == "not/in-any-catalog"
        assert w.bodies()[0]["model"] == "not/in-any-catalog"


async def test_a_tier_tier_call_in_standard_mode_is_refused_and_sends_nothing(world):
    w = await world()
    result = await w.call(ASK, query="q", tier="light")
    assert result.is_error and result.structured_content["category"] == "invalid_request"
    assert "tier" in result.structured_content["message"] and w.bodies() == []


@pytest.mark.parametrize(
    "extra", [{"tier": "light", "depth": "low"}, {"tier": "light", "model": "x/y"}]
)
async def test_conflicting_selectors_are_refused_with_guidance(world, extra):
    w = await world(**CUSTOM)
    result = await w.call(ASK, query="q", **extra)
    text = result.structured_content["message"]
    assert result.is_error and "cannot be combined" in text and "neither" in text
    assert w.bodies() == []


async def test_search_false_is_allowed_on_the_default_route(world):
    w = await world()
    await w.call(ASK, query="q", search=False)
    assert w.bodies()[0]["model"] == "perplexity/sonar" and "tools" not in w.bodies()[0]


async def test_research_is_unchanged_in_custom_mode(world):
    w = await world(**CUSTOM)
    research = await tool(w, "perplexity_research")
    assert "routing" not in research.output_schema.get("properties", {})
    assert "tier" not in research.input_schema["properties"]


# --- the chat tool ----------------------------------------------------------------------


async def test_chat_send_reports_routing_and_a_tier_changes_per_turn(chat_world):
    w = await chat_world(**CUSTOM)
    first = await w.call(CHAT, action="send", title="t", message="hi", tier="light")
    assert first.structured_content["routing"]["tier"] == "light"
    second = await w.call(CHAT, action="send", chat_id=1, message="and", tier="complex")
    assert second.structured_content["continuation"] == "chained"
    assert [b["model"] for b in w.bodies()] == ["x/light", "x/complex"]


async def test_chat_send_in_standard_mode_defaults_to_the_standard_model(chat_world):
    w = await chat_world()
    out = (await w.call(CHAT, action="send", title="t", message="hi")).structured_content
    assert out["routing"]["selected_by"] == "default" and out["depth"] is None


async def test_chat_conflicting_selectors_send_nothing(chat_world):
    w = await chat_world(**CUSTOM)
    result = await w.call(CHAT, action="send", title="t", message="hi", tier="light", depth="low")
    assert chat_category(result) == "invalid_request" and w.bodies() == []


async def test_list_read_and_delete_ignore_routing_selectors(chat_world):
    w = await chat_world()
    assert not (await w.call(CHAT, action="list", tier="light", depth="low")).is_error


# --- descriptions -----------------------------------------------------------------------


@pytest.mark.parametrize("name", [ASK, CHAT])
async def test_descriptions_state_the_mode_and_the_default_model(world, name):
    w = await world()
    text = (await tool(w, name)).description
    assert "standard" in text and "perplexity/sonar" in text
    assert "$0.001 to $0.002" in text  # the per-depth costs stay
    w = await world(**CUSTOM)
    text = (await tool(w, name)).description
    assert "custom" in text and "x/standard" in text and "x/light" in text and "x/complex" in text


async def test_the_search_parameter_no_longer_says_it_needs_a_model(world):
    w = await world()
    props = (await tool(w, ASK)).input_schema["properties"]
    assert "needs model" not in props["search"]["description"]
    assert "tier" in props and "custom" in props["tier"]["description"]


# --- wiring: one usage event per call, per mode and per source (task 4.1) ----------------


async def test_every_routed_call_makes_exactly_one_event_with_the_requested_preset(world, tmp_path):
    calls = [
        ({}, {}),  # default, standard mode
        ({}, {"depth": "low"}),
        ({}, {"model": "vendor/explicit"}),
        (CUSTOM, {}),
        (CUSTOM, {"tier": "complex"}),
        (CUSTOM, {"depth": "medium"}),
        (CUSTOM, {"model": "vendor/explicit"}),
    ]
    expected_presets = [None, "low", None, None, None, "medium", None]
    for i, ((settings, selectors), preset) in enumerate(zip(calls, expected_presets, strict=True)):
        # a database of its own per call: the fixture's response id would dedupe the events
        w = await world(data_dir=tmp_path / f"db{i}", **settings)
        result = await w.call(ASK, query="q", **selectors)
        assert not result.is_error, result.structured_content
        events = await w.events()
        assert len(events) == 1 and events[0][3] == preset, (settings, selectors, events)
        assert len(w.bodies()) == 1


async def test_refused_selector_combinations_make_no_event_and_no_request(world):
    w = await world(**CUSTOM)
    for selectors in (
        {"tier": "light", "depth": "low"},
        {"tier": "light", "model": "x/y"},
        {"depth": "low", "model": "x/y"},
        {"tier": "huge"},
        {"depth": "high"},
    ):
        assert (await w.call(ASK, query="q", **selectors)).is_error
    assert await w.events() == [] and w.bodies() == []
    assert await w.count("projects") == 0


# --- Gate 2 findings: stored row, anthropic cap, default-route shape -------------------------


async def test_a_model_route_stores_a_null_preset_and_an_old_fast_row_still_reads(chat_world):
    w = await chat_world()
    await w.call(CHAT, action="send", title="t", message="hi")
    rows = await w.rows("SELECT preset FROM chat_messages WHERE role = 'assistant'")
    assert rows == [(None,)]
    await w.call(CHAT, action="send", chat_id=1, message="and", depth="fast")
    rows = await w.rows("SELECT preset FROM chat_messages WHERE role = 'assistant' ORDER BY id")
    assert rows == [(None,), ("fast",)]
    read = await w.call(CHAT, action="read", chat_id=1)
    assert [
        m["preset"] for m in read.structured_content["messages"] if m["role"] == "assistant"
    ] == [
        None,
        "fast",
    ]


async def test_an_anthropic_tier_and_default_route_are_shaped_like_an_explicit_model(world):
    w = await world(
        routing="custom",
        tier_light="x/l",
        tier_standard="x/s",
        tier_complex="anthropic/claude-sonnet-5-5",
    )
    await w.call(ASK, query="q", tier="complex")
    await w.call(ASK, query="q")  # the standard tier, no cap
    capped, plain = w.bodies()
    assert capped["max_output_tokens"] == 4096 and "max_output_tokens" not in plain
    for body in (capped, plain):
        assert body["tools"] == [{"type": "web_search"}] and body["max_steps"] == 3
    w2 = await world(model="anthropic/claude-sonnet-5-5")
    await w2.call(ASK, query="q")
    default = w2.bodies()[0]
    assert default["max_output_tokens"] == 4096 and default["tools"] and default["max_steps"] == 3

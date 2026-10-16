"""routing-rules-v1 task 3.1: dynamic mode through ``build_server`` with a request-capturing
``MockTransport``: ``perplexity_ask`` and ``perplexity_chat`` send, the follow-up floor and the
order of errors."""

import pytest
from agent_support import make_world, respond_with
from chat_support import TOOL as CHAT
from chat_support import TURN_A, TURN_B, category, message, variant
from fastmcp import Client

ASK = "perplexity_ask"
DYNAMIC = {"routing": "dynamic"}
LOOKUP = "What is the latest stable Python release?"
ANALYSIS = "Compare two designs and evaluate their trade-offs."
ORDINARY = "Tell me about otters"
SHORT = "and in 2025?"


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(**settings):
        w = await make_world(
            make_settings, respond_with("agent_fast.json"), **{**DYNAMIC, **settings}
        )
        made.append(w)
        return w

    yield build
    for w in made:
        await w.aclose()


def routing_of(result):
    assert not result.is_error, result.structured_content
    return result.structured_content["routing"]


# --- ask ---------------------------------------------------------------------------------


async def test_a_lookup_goes_to_the_fast_preset(world):
    w = await world()
    routing = routing_of(await w.call(ASK, query=LOOKUP))
    assert routing == {
        "mode": "dynamic",
        "tier": "light",
        "model": None,
        "selected_by": "classifier",
        "classifier": "rules",
        "reason": "short lookup",
    }
    body = w.bodies()[0]
    assert body["preset"] == "fast" and "model" not in body


async def test_an_analysis_goes_to_the_medium_preset(world):
    w = await world()
    routing = routing_of(await w.call(ASK, query=ANALYSIS))
    assert (routing["tier"], routing["selected_by"], routing["model"]) == (
        "complex",
        "classifier",
        None,
    )
    assert routing["reason"] == "3 analysis terms"
    assert w.bodies()[0]["preset"] == "medium"


async def test_an_ordinary_question_runs_the_standard_model_shaped_like_an_explicit_model(world):
    w = await world()
    routing = routing_of(await w.call(ASK, query=ORDINARY))
    assert (routing["tier"], routing["model"], routing["reason"]) == (
        "standard",
        "perplexity/sonar",
        "no signals",
    )
    body = w.bodies()[0]
    assert body["model"] == "perplexity/sonar" and "preset" not in body
    assert body["tools"] == [{"type": "web_search"}] and body["max_steps"] == 3


async def test_a_replaced_tier_runs_its_model_as_an_explicit_model_call_would(world):
    w = await world(tier_complex="anthropic/claude-opus-5-5")
    routing = routing_of(await w.call(ASK, query=ANALYSIS))
    assert (routing["tier"], routing["model"]) == ("complex", "anthropic/claude-opus-5-5")
    body = w.bodies()[0]
    assert body["model"] == "anthropic/claude-opus-5-5" and "preset" not in body
    assert body["tools"] == [{"type": "web_search"}] and body["max_steps"] == 3
    assert body["max_output_tokens"] == 4096


async def test_a_preset_route_request_equals_the_depth_request(world):
    w = await world()
    await w.call(ASK, query=LOOKUP)
    await w.call(ASK, query=LOOKUP, depth="fast")
    routed, explicit = w.bodies()
    assert routed == explicit
    await w.call(ASK, query=ANALYSIS, domains=["python.org"])
    await w.call(ASK, query=ANALYSIS, depth="medium", domains=["python.org"])
    routed, explicit = w.bodies()[2:]
    assert routed == explicit and routed["preset"] == "medium"


async def test_classifying_makes_no_upstream_request_and_records_one_event(world, tmp_path):
    for i, (query, preset) in enumerate([(LOOKUP, "fast"), (ANALYSIS, "medium"), (ORDINARY, None)]):
        w = await world(data_dir=tmp_path / f"db{i}")
        assert not (await w.call(ASK, query=query)).is_error
        events = await w.events()
        assert len(w.requests) == 1 and len(events) == 1
        assert events[0][3] == preset  # the preset the event records is the resolved one


async def test_an_explicit_selector_wins_and_nothing_is_classified(world):
    w = await world()
    assert routing_of(await w.call(ASK, query=LOOKUP, depth="low"))["selected_by"] == "depth"
    by_model = routing_of(await w.call(ASK, query=LOOKUP, model="vendor/x"))
    assert (by_model["selected_by"], by_model["model"], by_model["reason"]) == (
        "model",
        "vendor/x",
        None,
    )
    by_tier = routing_of(await w.call(ASK, query=LOOKUP, tier="complex"))
    assert (by_tier["selected_by"], by_tier["tier"], by_tier["classifier"]) == (
        "tier",
        "complex",
        None,
    )
    assert [b.get("preset") for b in w.bodies()] == ["low", None, "medium"]


async def test_search_false_runs_the_standard_model_with_no_tools(world):
    w = await world()
    routing = routing_of(await w.call(ASK, query=LOOKUP, search=False))
    assert routing == {
        "mode": "dynamic",
        "tier": "standard",
        "model": "perplexity/sonar",
        "selected_by": "default",
        "classifier": None,
        "reason": "search off",
    }
    body = w.bodies()[0]
    assert body["model"] == "perplexity/sonar" and "tools" not in body and "preset" not in body


async def test_search_false_with_a_preset_tier_is_refused_and_sends_nothing(world):
    w = await world()
    result = await w.call(ASK, query=LOOKUP, tier="light", search=False)
    assert result.is_error and result.structured_content["category"] == "invalid_request"
    text = result.structured_content["message"]
    assert "tier" in text and "search" in text and "always searches" in text
    assert w.bodies() == [] and await w.events() == []


async def test_search_false_with_a_replaced_tier_model_is_allowed(world):
    w = await world(tier_light="x/light")
    routing = routing_of(await w.call(ASK, query=LOOKUP, tier="light", search=False))
    assert routing["model"] == "x/light" and "tools" not in w.bodies()[0]


async def test_dynamic_refusals_keep_their_order_and_send_nothing(world):
    w = await world()
    for selectors in (
        {"tier": "light", "depth": "low"},
        {"tier": "huge"},
        {"depth": "high"},
        {"depth": "low", "model": "x/y"},
    ):
        assert (await w.call(ASK, query=LOOKUP, **selectors)).is_error
    assert w.bodies() == [] and await w.events() == []


async def test_research_is_unchanged_in_dynamic_mode(world):
    w = await world()
    async with Client(w.server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert "routing" not in tools["perplexity_research"].output_schema.get("properties", {})
    assert "tier" not in tools["perplexity_research"].input_schema["properties"]


# --- chat ---------------------------------------------------------------------------------


@pytest.fixture
def dchat(chat_world):
    async def build(responder=None, **settings):
        return await chat_world(responder, **{**DYNAMIC, **settings})

    return build


async def send(w, **kw):
    result = await w.call(CHAT, action="send", **kw)
    assert not result.is_error, result.structured_content
    return result.structured_content


async def stored_presets(w):
    return await w.rows(
        "SELECT preset, model FROM chat_messages WHERE role = 'assistant' ORDER BY id"
    )


async def test_a_new_chat_is_classified_and_stores_the_preset(dchat):
    w = await dchat()
    out = await send(w, title="t", message=LOOKUP)
    assert out["routing"]["tier"] == "light" and out["routing"]["classifier"] == "rules"
    assert w.bodies()[0]["preset"] == "fast"
    assert (await stored_presets(w))[0][0] == "fast"
    assert len(await w.events()) == 1


async def test_a_short_follow_up_to_a_complex_chat_stays_complex(dchat):
    w = await dchat()
    await send(w, title="t", message=ANALYSIS)
    out = await send(w, chat_id=1, message=SHORT)
    routing = out["routing"]
    assert (routing["tier"], routing["selected_by"], routing["classifier"]) == (
        "complex",
        "classifier",
        "rules",
    )
    assert "held at complex" in routing["reason"]
    assert [b["preset"] for b in w.bodies()] == ["medium", "medium"]
    assert out["continuation"] == "chained"


async def test_a_longer_question_raises_the_tier(dchat):
    w = await dchat()
    await send(w, title="t", message=LOOKUP)
    out = await send(w, chat_id=1, message=ANALYSIS)
    assert out["routing"]["tier"] == "complex" and "held" not in out["routing"]["reason"]
    assert [b["preset"] for b in w.bodies()] == ["fast", "medium"]


async def test_the_floor_holds_at_standard_too(dchat):
    w = await dchat()
    await send(w, title="t", message=ORDINARY)
    out = await send(w, chat_id=1, message=LOOKUP)
    assert out["routing"]["tier"] == "standard" and "held at standard" in out["routing"]["reason"]
    assert w.bodies()[1]["model"] == "perplexity/sonar"


async def test_an_explicit_selector_leaves_the_floor(dchat):
    w = await dchat()
    await send(w, title="t", message=ANALYSIS)
    out = await send(w, chat_id=1, message=SHORT, depth="fast")
    assert (out["routing"]["selected_by"], out["routing"]["reason"]) == ("depth", None)
    assert w.bodies()[1]["preset"] == "fast"
    out = await send(w, chat_id=1, message=SHORT, tier="light")
    assert out["routing"]["selected_by"] == "tier" and w.bodies()[2]["preset"] == "fast"


async def test_a_model_no_tier_uses_counts_as_standard(dchat):
    w = await dchat()
    await send(w, title="t", message=ORDINARY, model="vendor/explicit")
    assert (await stored_presets(w))[0][0] is None
    out = await send(w, chat_id=1, message=LOOKUP)
    assert out["routing"]["tier"] == "standard" and "held at standard" in out["routing"]["reason"]


async def test_a_tie_between_tiers_takes_the_highest(dchat):
    def reporting_x_same(request, n):
        import httpx2

        body = variant(TURN_A if n == 1 else TURN_B, f"resp_tie{n}")
        body["model"] = "x/same"
        return httpx2.Response(200, json=body)

    w = await dchat(reporting_x_same, tier_light="x/same", tier_complex="x/same")
    await send(w, title="t", message=ORDINARY, model="x/same")
    out = await send(w, chat_id=1, message=SHORT)
    assert out["routing"]["tier"] == "complex" and "held at complex" in out["routing"]["reason"]
    assert w.bodies()[1]["model"] == "x/same"


async def test_search_false_beats_the_floor_and_runs_the_standard_model(dchat):
    w = await dchat()
    await send(w, title="t", message=ANALYSIS)
    out = await send(w, chat_id=1, message=SHORT, search=False)
    routing = out["routing"]
    assert (routing["tier"], routing["selected_by"], routing["reason"]) == (
        "standard",
        "default",
        "search off",
    )
    body = w.bodies()[1]
    assert body["model"] == "perplexity/sonar" and "tools" not in body and "preset" not in body


async def test_search_false_with_a_preset_tier_is_refused_before_any_lookup(dchat):
    w = await dchat()
    result = await w.call(
        CHAT, action="send", chat_id=77, message=SHORT, tier="light", search=False
    )
    assert category(result) == "invalid_request"
    assert "tier" in message(result) and "search" in message(result)
    assert w.bodies() == []


async def test_errors_keep_their_order_for_a_nameless_follow_up(dchat):
    w = await dchat()
    missing = await w.call(CHAT, action="send", chat_id=77, message=SHORT)
    assert category(missing) == "not_found"
    for extra in (
        {"tier": "huge"},
        {"depth": "high"},
        {"max_output_tokens": 0},
        {"domains": ["a.com"], "search": False},
        {"recency": "decade"},
    ):
        result = await w.call(CHAT, action="send", chat_id=77, message=SHORT, **extra)
        assert category(result) == "invalid_request", extra
    blank = await w.call(CHAT, action="send", chat_id=77, message="   ")
    assert category(blank) == "invalid_request"
    assert w.bodies() == [] and await w.events() == []


async def test_a_replay_in_dynamic_mode_also_holds_the_tier(dchat):
    w = await dchat()
    await send(w, title="t", message=ANALYSIS)
    out = await send(w, chat_id=1, message=SHORT, replay=True)
    assert out["continuation"] == "replay" and out["routing"]["tier"] == "complex"
    assert w.bodies()[1]["preset"] == "medium"


def routing_properties(schema):
    """The properties of the ``routing`` field, wherever the schema keeps its definition."""
    node = schema["properties"]["routing"]
    nodes = [node, *node.get("anyOf", [])]
    for item in nodes:
        if "$ref" in item:
            return schema["$defs"][item["$ref"].rsplit("/", 1)[1]]["properties"]
        if "properties" in item:
            return item["properties"]
    raise AssertionError(node)


async def test_the_chat_result_schema_carries_the_new_routing_fields(dchat):
    w = await dchat()
    async with Client(w.server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    for name in (ASK, CHAT):
        schema = tools[name].output_schema
        assert {"reason", "classifier"} <= set(routing_properties(schema))

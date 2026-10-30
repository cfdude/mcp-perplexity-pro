"""Task 2.1 (routing-decisions-classifier): ``perplexity_ask`` and ``perplexity_chat`` send in
dynamic mode with ``PERPLEXITY_CLASSIFIER=decisions``, through ``build_server`` with a
path-aware ``MockTransport`` (the Decisions requests are counted apart from the Agent ones)."""

import json

import httpx2
import pytest
from agent_support import fixture, make_world
from chat_support import TOOL as CHAT
from chat_support import TURN_A, TURN_B, category, message

from mcp_perplexity_pro import routing_decisions
from mcp_perplexity_pro.routing import description_sentence, instructions_text

ASK = "perplexity_ask"
DECISIONS = {"routing": "dynamic", "classifier": "decisions"}
LOOKUP = "What is the latest stable Python release?"
ORDINARY = "Tell me about otters"
SHORT = "and in 2025?"
HEADLINE = {"light", "standard", "complex"}


def decision(choice, probability=0.9):
    return {
        "model": "pplx-decider-v1.1-27b",
        "answers": {
            "tier": {
                "type": "choice",
                "choice": choice,
                "confidence": probability,
                "probabilities": {t: (probability if t == choice else 0.05) for t in HEADLINE},
            }
        },
        "usage": {"input_tokens": 120, "output_tokens": 1},
    }


class Switchboard:
    """Routes each POST by path: ``/v1/decisions`` answers ``self.decisions`` (a body, a status
    pair or a callable), anything else answers the Agent turns in order."""

    def __init__(self, *, decisions=None, agent=(TURN_A, TURN_B)):
        self.decisions = decisions if decisions is not None else decision("standard")
        self.agent = agent
        self.agent_calls = 0

    def __call__(self, request, n):
        if request.url.path == "/v1/models":
            return httpx2.Response(200, json=fixture("models.json"))
        if request.url.path == "/v1/decisions":
            answer = self.decisions(request) if callable(self.decisions) else self.decisions
            if isinstance(answer, tuple):
                return httpx2.Response(answer[0], json=answer[1])
            return httpx2.Response(200, json=answer)
        self.agent_calls += 1
        item = self.agent[min(self.agent_calls, len(self.agent)) - 1]
        body = fixture(item) if isinstance(item, str) else item
        if self.agent_calls > 2:  # a third turn needs its own response id
            body = {**body, "id": f"resp_extra{self.agent_calls}"}
        return httpx2.Response(200, json=body)


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(board=None, **settings):
        board = board or Switchboard()
        w = await make_world(make_settings, board, **{**DECISIONS, **settings})
        made.append(w)
        return w, board

    yield build
    for w in made:
        await w.aclose()


def decide_requests(w):
    return [r for r in w.requests if r.url.path == "/v1/decisions"]


def agent_bodies(w):
    return [json.loads(r.content) for r in w.requests if r.url.path != "/v1/decisions"]


def routing_of(result):
    assert not result.is_error, result.structured_content
    return result.structured_content["routing"]


# --- ask ---------------------------------------------------------------------------------


async def test_a_nameless_ask_is_classified_by_the_decider_and_routed(world):
    w, _ = await world(Switchboard(decisions=decision("light", 0.93)))
    result = await w.call(ASK, query=ORDINARY)  # the rules would say standard
    assert routing_of(result) == {
        "mode": "dynamic",
        "tier": "light",
        "model": None,
        "selected_by": "classifier",
        "classifier": "decisions",
        "reason": "decisions: light (0.93)",
    }
    assert len(decide_requests(w)) == 1 and agent_bodies(w)[0]["effort"] == "fast"


async def test_a_complex_answer_runs_the_medium_preset(world):
    w, _ = await world(Switchboard(decisions=decision("complex", 0.95)))
    assert routing_of(await w.call(ASK, query=SHORT))["tier"] == "complex"
    assert agent_bodies(w)[0]["effort"] == "medium"


async def test_two_events_one_agent_and_one_decisions_both_under_the_ask_tool(world):
    w, _ = await world(Switchboard(decisions=decision("light")))
    assert not (await w.call(ASK, query=ORDINARY, project="alpha")).is_error
    events = await w.events()
    assert sorted((e[0], e[1], e[2], e[6]) for e in events) == [
        (ASK, "agent", "ok", "alpha"),
        (ASK, "decisions", "ok", "alpha"),
    ]
    decisions_event = next(e for e in events if e[1] == "decisions")
    assert decisions_event[8] == "computed" and decisions_event[7] == 120 * 20


async def test_a_failed_classification_falls_back_to_the_rules_and_the_ask_is_answered(world):
    w, _ = await world(Switchboard(decisions=(429, {"error": {"message": "slow"}})))
    result = await w.call(ASK, query=LOOKUP)
    routing = routing_of(result)
    assert (routing["tier"], routing["classifier"]) == ("light", "rules")
    assert "rate_limited" in routing["reason"] and len(routing["reason"]) <= 120
    statuses = sorted((e[1], e[2]) for e in await w.events())
    assert statuses == [("agent", "ok"), ("decisions", "rate_limited")]


async def test_a_weak_answer_takes_the_higher_of_the_two_tiers(world):
    w, _ = await world(Switchboard(decisions=decision("light", 0.4)))
    routing = routing_of(await w.call(ASK, query="Compare two designs and evaluate trade-offs."))
    assert (routing["tier"], routing["classifier"]) == ("complex", "rules")
    assert "weak" in routing["reason"]


@pytest.mark.parametrize(
    "selectors", [{"depth": "fast"}, {"tier": "light"}, {"model": "vendor/x"}], ids=str
)
async def test_an_explicit_selector_makes_no_decisions_request(world, selectors):
    w, _ = await world()
    routing = routing_of(await w.call(ASK, query=ORDINARY, **selectors))
    assert routing["classifier"] is None and routing["reason"] is None
    assert decide_requests(w) == []
    assert [e[1] for e in await w.events()] == ["agent"]


async def test_search_off_makes_no_decisions_request_and_runs_the_standard_model(world):
    w, _ = await world()
    routing = routing_of(await w.call(ASK, query=LOOKUP, search=False))
    assert (routing["tier"], routing["classifier"], routing["reason"]) == (
        "standard",
        None,
        "search off",
    )
    assert decide_requests(w) == [] and agent_bodies(w)[0]["model"] == "perplexity/sonar"


@pytest.mark.parametrize(
    "bad",
    [
        {"max_output_tokens": 0},
        {"recency": "decade"},
        {"domains": ["a.com"], "search": False},
        {"country": "usa"},
        {"project": "Bad Name!"},
    ],
    ids=str,
)
async def test_an_invalid_call_makes_no_decisions_request_and_records_nothing(world, bad):
    w, _ = await world()
    result = await w.call(ASK, query=LOOKUP, **bad)
    assert category(result) == "invalid_request"
    assert w.requests == [] and await w.events() == []


async def test_the_default_classifier_never_asks_the_decider(world):
    w, _ = await world(classifier="rules")
    routing = routing_of(await w.call(ASK, query=ORDINARY))
    assert routing["classifier"] == "rules" and decide_requests(w) == []


async def test_outside_dynamic_mode_the_decider_is_never_asked(world):
    for mode, extra in (
        ("standard", {}),
        ("custom", {"tier_light": "a/a", "tier_standard": "a/b", "tier_complex": "a/c"}),
    ):
        w, _ = await world(routing=mode, **extra)
        assert not (await w.call(ASK, query=ORDINARY)).is_error
        assert decide_requests(w) == []


async def test_the_classification_comes_before_the_agent_request(world):
    w, _ = await world()
    assert not (await w.call(ASK, query=ORDINARY)).is_error
    paths = [r.url.path for r in w.requests]
    assert paths == ["/v1/decisions", "/v1/agent"]


# --- chat --------------------------------------------------------------------------------


async def send(w, **kw):
    result = await w.call(CHAT, action="send", **kw)
    assert not result.is_error, result.structured_content
    return result.structured_content


async def test_a_new_chat_send_is_classified_and_recorded_under_the_chat_tool(world):
    w, _ = await world(Switchboard(decisions=decision("light", 0.9)))
    out = await send(w, title="t", message=ORDINARY, project="alpha")
    assert out["routing"]["tier"] == "light" and out["routing"]["classifier"] == "decisions"
    assert agent_bodies(w)[0]["effort"] == "fast"
    events = await w.events()
    assert sorted((e[0], e[1], e[6]) for e in events) == [
        (CHAT, "agent", "alpha"),
        (CHAT, "decisions", "alpha"),
    ]


async def test_the_follow_up_floor_holds_over_a_light_answer(world):
    answers = iter([decision("standard"), decision("light", 0.95)])
    w, _ = await world(Switchboard(decisions=lambda request: next(answers)))
    await send(w, title="t", message=ORDINARY)
    out = await send(w, chat_id=1, message=SHORT)
    routing = out["routing"]
    assert (routing["tier"], routing["classifier"]) == ("standard", "decisions")
    assert "held at standard" in routing["reason"]
    assert len(decide_requests(w)) == 2


async def test_a_follow_up_whose_floor_is_complex_makes_no_decisions_request(world):
    w, _ = await world(Switchboard(decisions=decision("complex", 0.95)))
    await send(w, title="t", message="Compare two designs and evaluate trade-offs.")
    assert len(decide_requests(w)) == 1
    out = await send(w, chat_id=1, message=SHORT)
    assert out["routing"]["tier"] == "complex"
    assert len(decide_requests(w)) == 1  # the floor decided; nothing could change the route
    assert [e[1] for e in await w.events()].count("decisions") == 1


async def test_an_unknown_chat_makes_no_decisions_request(world):
    w, _ = await world()
    result = await w.call(CHAT, action="send", chat_id=77, message=SHORT)
    assert category(result) == "not_found"
    assert w.requests == [] and await w.events() == []


async def test_a_chat_with_no_response_to_continue_makes_no_decisions_request(world):
    from chat_support import seed_chat

    w, _ = await world()
    chat_id = await seed_chat(w, "default", "t", turns=1)
    # strip the stored response id so there is nothing to chain from
    await w.rows("SELECT 1")
    async with w.engine.begin() as conn:
        from sqlalchemy import text

        await conn.execute(text("UPDATE chat_messages SET response_id = NULL"))
    result = await w.call(CHAT, action="send", chat_id=chat_id, message=SHORT)
    assert category(result) == "invalid_request" and "replay" in message(result)
    assert decide_requests(w) == []


async def test_an_invalid_project_name_is_refused_before_any_request(world):
    w, _ = await world()
    result = await w.call(CHAT, action="send", title="t", message=ORDINARY, project="Bad Name!")
    assert category(result) == "invalid_request"
    assert w.requests == [] and await w.events() == []


async def test_an_invalid_chat_send_makes_no_decisions_request(world):
    w, _ = await world()
    for extra in ({"max_output_tokens": 0}, {"recency": "decade"}):
        result = await w.call(CHAT, action="send", title="t", message=ORDINARY, **extra)
        assert category(result) == "invalid_request"
    assert w.requests == []


@pytest.mark.parametrize(
    "extra", [{"depth": "fast"}, {"tier": "light"}, {"search": False}], ids=str
)
async def test_a_chat_send_that_names_something_makes_no_decisions_request(world, extra):
    w, _ = await world()
    await send(w, title="t", message=ORDINARY, **extra)
    assert decide_requests(w) == []


async def test_a_chat_classification_failure_falls_back_to_the_rules(world):
    w, _ = await world(Switchboard(decisions=(403, {"error": {"message": "no"}})))
    out = await send(w, title="t", message=LOOKUP)
    assert (out["routing"]["tier"], out["routing"]["classifier"]) == ("light", "rules")
    assert "forbidden" in out["routing"]["reason"]


# --- telling the agent -------------------------------------------------------------------


def test_the_instructions_and_description_name_the_decisions_classifier_and_its_fallback(
    make_settings,
):
    settings = make_settings(**DECISIONS)
    for text in (instructions_text(settings), description_sentence(settings)):
        assert "Decisions" in text and "rules replace" in text
        assert settings.api_key.get_secret_value() not in text


def test_the_rules_classifier_is_named_too(make_settings):
    settings = make_settings(routing="dynamic")
    for text in (instructions_text(settings), description_sentence(settings)):
        assert "Classifier: rules" in text and "Decisions" not in text


async def test_the_server_carries_the_classifier_in_its_instructions(world):
    w, _ = await world()
    assert w.server.instructions == instructions_text(w.settings)
    assert "Decisions" in w.server.instructions and "rules replace" in w.server.instructions


async def test_the_models_routing_section_names_the_classifier_and_the_decider(world):
    w, _ = await world()
    result = await w.call("perplexity_models")
    section = result.structured_content["routing"]
    assert (
        section["classifier"] == "decisions" and section["decider_model"] == "pplx-decider-v1.1-27b"
    )
    assert "classifier decisions" in result.content[0].text
    w, _ = await world(classifier="rules")
    section = (await w.call("perplexity_models")).structured_content["routing"]
    assert section["classifier"] == "rules" and section["decider_model"] is None


async def test_the_help_routing_topic_names_the_classifier_and_its_fallback(world):
    w, _ = await world()
    result = await w.call("perplexity_help", action="topic", name="routing")
    text = result.content[0].text
    assert "Decisions" in text and "rules replace" in text and "fixed rules" not in text
    assert len(text.encode()) <= 3000 and text.isascii()


def test_the_bound_constant_is_three_seconds():
    assert routing_decisions.BOUND_SECONDS == 3.0

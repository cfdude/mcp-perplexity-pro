"""The fixed order of a model call and its three hooks (``call_flow``; task 5.3a).

Stubs record where each step ran: selector and tier errors, the attachment-parse hook, a
provisional resolve and option validation, the real resolve, the gate hook, the Decisions
request, the second resolve and the gate hook again on the final route. The hooks are no-ops
today; ``resolve`` accepts ``required_input`` and ``provisional`` and ignores both.
"""

from pathlib import Path

import pytest
from agent_support import make_world, respond_with
from chat_support import TOOL as CHAT
from chat_support import sequence, variant

from mcp_perplexity_pro import call_flow
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.routing import resolve
from mcp_perplexity_pro.rules import Classification
from mcp_perplexity_pro.tools import ask as ask_tool
from mcp_perplexity_pro.tools import chat as chat_tool

ASK = "perplexity_ask"
PIN = "x/pinned"


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder=None, **settings):
        w = await make_world(
            make_settings, responder or respond_with("agent_fast.json"), **settings
        )
        made.append(w)
        return w

    yield build
    for w in made:
        await w.aclose()


class Trace:
    """Records the steps of one call and lets a test make a step refuse."""

    def __init__(self, monkeypatch, module):
        self.events: list[str] = []
        self.gated: list[tuple[str | None, str | None, frozenset[str]]] = []
        self.refuse: dict[str, PerplexityError] = {}
        real_resolve, real_build = module.resolve, module.build_request
        real_check, real_classify = module.check_selectors, module.classify_dynamic

        def check(*args, **kwargs):
            self.events.append("selectors")
            return real_check(*args, **kwargs)

        def resolve_(*args, **kwargs):
            if kwargs.get("provisional"):
                step = "resolve:provisional"
            elif kwargs.get("classification") is not None:
                step = "resolve:decided"
            else:
                step = "resolve:real"
            self.events.append(step)
            if step in self.refuse:
                raise self.refuse[step]
            return real_resolve(*args, **kwargs)

        def build(*args, **kwargs):
            self.events.append("build")
            return real_build(*args, **kwargs)

        async def classify(*args, **kwargs):
            self.events.append("classify")
            return self.classification

        def parse(attachments=None):
            self.events.append("parse")
            if "parse" in self.refuse:
                raise self.refuse["parse"]
            return self.kinds

        def gate(app, route, kinds):
            self.events.append("gate")
            self.gated.append((route.model, route.preset, kinds))
            if "gate" in self.refuse:
                raise self.refuse["gate"]

        self.kinds: frozenset[str] = frozenset()
        self.classification = Classification("complex", "stub", "decisions")
        monkeypatch.setattr(module, "check_selectors", check)
        monkeypatch.setattr(module, "resolve", resolve_)
        monkeypatch.setattr(module, "build_request", build)
        monkeypatch.setattr(module, "classify_dynamic", classify)
        monkeypatch.setattr(call_flow, "parse_attachments", parse)
        monkeypatch.setattr(call_flow, "gate_route", gate)
        self._real_classify = real_classify


def refusal(text):
    return PerplexityError("invalid_request", text)


# --- ask --------------------------------------------------------------------------------------


async def test_an_ask_runs_the_steps_in_order_and_gates_the_real_route_once(world, monkeypatch):
    trace = Trace(monkeypatch, ask_tool)
    w = await world()
    result = await w.call(ASK, query="hello there")
    assert not result.is_error, result.content
    assert trace.events == [
        "selectors",
        "parse",
        "resolve:provisional",
        "build",
        "resolve:real",
        "gate",
        "build",
    ]
    assert trace.gated == [("perplexity/sonar", None, frozenset())]


async def test_a_named_model_and_a_named_depth_follow_the_same_order(world, monkeypatch):
    trace = Trace(monkeypatch, ask_tool)
    w = await world()
    for arguments in ({"model": "vendor/m"}, {"depth": "fast"}):
        trace.events.clear()
        assert not (await w.call(ASK, query="q", **arguments)).is_error
        assert trace.events[:3] == ["selectors", "parse", "resolve:provisional"]
        assert trace.events.count("gate") == 1 and "classify" not in trace.events


async def test_the_parsed_kinds_reach_the_real_resolve_and_the_gate(world, monkeypatch):
    trace = Trace(monkeypatch, ask_tool)
    trace.kinds = frozenset({"image"})
    seen = []
    real = ask_tool.resolve

    def spy(*args, **kwargs):
        seen.append((kwargs.get("provisional", False), kwargs.get("required_input")))
        return real(*args, **kwargs)

    monkeypatch.setattr(ask_tool, "resolve", spy)
    w = await world()
    assert not (await w.call(ASK, query="q")).is_error
    assert seen == [(True, frozenset({"image"})), (False, frozenset({"image"}))]
    assert trace.gated[-1][2] == frozenset({"image"})


async def test_the_decisions_request_runs_after_the_gate_and_the_final_route_is_gated_again(
    world, monkeypatch
):
    trace = Trace(monkeypatch, ask_tool)  # the classifier says complex; the pin replaces the model
    w = await world(routing="dynamic", classifier="decisions", tier_complex=PIN)
    result = await w.call(ASK, query="hello there")
    assert not result.is_error, result.content
    assert trace.events == [
        "selectors",
        "parse",
        "resolve:provisional",
        "build",
        "resolve:real",
        "gate",
        "build",
        "classify",
        "resolve:decided",
        "gate",
        "build",
    ]
    assert [g[0] for g in trace.gated] == ["perplexity/sonar", PIN]
    assert w.bodies()[0]["model"] == PIN


async def test_the_final_route_is_not_gated_again_when_the_second_resolve_changed_nothing(
    world, monkeypatch
):
    trace = Trace(monkeypatch, ask_tool)
    trace.classification = Classification("standard", "stub", "decisions")
    w = await world(routing="dynamic", classifier="decisions")
    assert not (await w.call(ASK, query="hello there")).is_error
    assert trace.events.count("gate") == 1 and trace.events[-3:] == [
        "classify",
        "resolve:decided",
        "build",
    ]


async def test_a_bad_selector_fails_before_the_attachment_parse(world, monkeypatch):
    trace = Trace(monkeypatch, ask_tool)
    trace.refuse["parse"] = refusal("attachments: refused")
    w = await world(routing="dynamic")
    result = await w.call(ASK, query="q", tier="huge")
    assert result.is_error and "tier" in result.structured_content["message"]
    assert trace.events == ["selectors"]  # nothing was parsed, resolved or built
    assert w.bodies() == []


async def test_a_bad_attachment_fails_before_option_validation_and_any_resolve(world, monkeypatch):
    trace = Trace(monkeypatch, ask_tool)
    trace.refuse["parse"] = refusal("attachments: refused")
    w = await world()
    result = await w.call(ASK, query="q", recency="century")  # also a bad option
    assert "attachments" in result.structured_content["message"]
    assert trace.events == ["selectors", "parse"] and w.bodies() == []


@pytest.mark.parametrize("step", ["resolve:real", "gate"])
async def test_a_bad_option_beats_a_refusal_of_the_real_resolve_or_the_gate(
    world, monkeypatch, step
):
    trace = Trace(monkeypatch, ask_tool)
    trace.refuse[step] = refusal(f"{step}: refused")
    w = await world()
    result = await w.call(ASK, query="q", recency="century")
    assert result.is_error and "recency" in result.structured_content["message"]
    assert step not in trace.events  # validation stopped the call first
    assert w.bodies() == []


@pytest.mark.parametrize("step", ["resolve:real", "gate"])
async def test_a_refusal_after_a_valid_call_sends_nothing(world, monkeypatch, step):
    trace = Trace(monkeypatch, ask_tool)
    trace.refuse[step] = refusal(f"{step}: refused")
    w = await world()
    result = await w.call(ASK, query="q")
    assert result.is_error and step in result.structured_content["message"]
    assert w.bodies() == [] and await w.count("usage_events") == 0


async def test_a_refusal_at_the_gate_happens_before_the_decisions_request(world, monkeypatch):
    trace = Trace(monkeypatch, ask_tool)
    trace.refuse["gate"] = refusal("gate: refused")
    w = await world(routing="dynamic", classifier="decisions")
    result = await w.call(ASK, query="q")
    assert result.is_error and "classify" not in trace.events and w.bodies() == []


async def test_a_refusal_of_the_final_route_comes_after_the_decisions_request(world, monkeypatch):
    trace = Trace(monkeypatch, ask_tool)
    calls = []

    def gate(app, route, kinds):
        calls.append(route.model)
        if route.model == PIN:
            raise refusal("gate: the pinned model refuses")

    monkeypatch.setattr(call_flow, "gate_route", gate)
    w = await world(routing="dynamic", classifier="decisions", tier_complex=PIN)
    result = await w.call(ASK, query="hello there")
    assert result.is_error and "pinned" in result.structured_content["message"]
    assert "classify" in trace.events and calls == ["perplexity/sonar", PIN]
    assert w.bodies() == []


# --- chat -------------------------------------------------------------------------------------


@pytest.fixture
def chat_responses():
    return sequence("agent_chat_turn_a.json", variant("agent_chat_turn_a.json", "resp_chat-2"))


async def test_a_new_chat_send_runs_the_steps_in_order(world, monkeypatch, chat_responses):
    trace = Trace(monkeypatch, chat_tool)
    w = await world(chat_responses)
    result = await w.call(CHAT, action="send", title="t", message="hello there")
    assert not result.is_error, result.content
    assert trace.events == [
        "selectors",
        "parse",
        "resolve:provisional",
        "build",
        "resolve:real",
        "gate",
        "build",
    ]
    assert trace.gated == [("perplexity/sonar", None, frozenset())]


async def test_a_chat_send_with_the_decisions_classifier_gates_again_on_a_changed_route(
    world, monkeypatch, chat_responses
):
    trace = Trace(monkeypatch, chat_tool)
    w = await world(chat_responses, routing="dynamic", classifier="decisions", tier_complex=PIN)
    result = await w.call(CHAT, action="send", title="t", message="hello there")
    assert not result.is_error, result.content
    assert trace.events[-6:] == [
        "resolve:real",
        "gate",
        "classify",
        "resolve:decided",
        "gate",
        "build",
    ]
    assert [g[0] for g in trace.gated] == ["perplexity/sonar", PIN]


async def test_a_bad_chat_selector_fails_before_the_parse_and_a_bad_option_beats_the_gate(
    world, monkeypatch, chat_responses
):
    trace = Trace(monkeypatch, chat_tool)
    w = await world(chat_responses)
    result = await w.call(CHAT, action="send", title="t", message="q", depth="fast", model="m/x")
    assert result.is_error and trace.events == ["selectors"]
    trace.events.clear()
    trace.refuse["gate"] = refusal("gate: refused")
    result = await w.call(CHAT, action="send", title="t", message="q", recency="century")
    assert "recency" in result.structured_content["message"] and "gate" not in trace.events
    assert w.bodies() == []


async def test_a_chained_send_gates_on_new_and_inherited_kinds_and_a_replay_on_new_only(
    world, monkeypatch, chat_responses
):
    trace = Trace(monkeypatch, chat_tool)
    trace.kinds = frozenset({"document"})
    monkeypatch.setattr(call_flow, "inherited_kinds", lambda chat: frozenset({"image"}))
    w = await world(chat_responses)
    assert not (await w.call(CHAT, action="send", title="t", message="first")).is_error
    assert trace.gated[-1][2] == frozenset({"document"})  # a new chat inherits nothing
    chained = await w.call(CHAT, action="send", chat_id=1, message="second")
    assert not chained.is_error, chained.content
    assert trace.gated[-1][2] == frozenset({"document", "image"})
    replay = await w.call(CHAT, action="send", chat_id=1, message="third", replay=True)
    assert not replay.is_error, replay.content
    assert trace.gated[-1][2] == frozenset({"document"})  # a replay resends no earlier file


# --- the hooks and resolve themselves ---------------------------------------------------------


def test_the_hooks_are_no_ops_and_inherited_kinds_is_the_empty_set():
    assert call_flow.parse_attachments() == frozenset()
    assert call_flow.parse_attachments(None) == frozenset()
    assert call_flow.inherited_kinds(object()) == frozenset()
    assert call_flow.inherited_kinds(None) == frozenset()
    route = resolve_for("standard")
    assert call_flow.gate_route(object(), route, frozenset({"image"})) is None


def resolve_for(mode, **kwargs):
    from mcp_perplexity_pro.settings import Settings

    extra = {}
    if mode == "custom":
        extra = dict(tier_light="x/l", tier_standard="x/s", tier_complex="x/c")
    settings = Settings(api_key="test-dummy-api-key", routing=mode, **extra)
    return resolve(settings, **kwargs)


def test_required_kinds_adds_inherited_kinds_for_a_chained_send_only(monkeypatch):
    monkeypatch.setattr(call_flow, "inherited_kinds", lambda chat: frozenset({"image"}))
    new = frozenset({"document"})
    chat = object()
    assert call_flow.required_kinds(new, chat, replay=False) == {"document", "image"}
    assert call_flow.required_kinds(new, chat, replay=True) == new
    assert call_flow.required_kinds(new, None, replay=False) == new  # a new chat has no history


@pytest.mark.parametrize("mode", ["standard", "custom", "dynamic"])
@pytest.mark.parametrize(
    "selectors",
    [{}, {"model": "v/m"}, {"depth": "low"}, {"tier": "light"}, {"text": "compare and evaluate"}],
)
def test_required_input_and_provisional_change_no_route(mode, selectors):
    if mode == "standard" and "tier" in selectors:
        pytest.skip("a tier is refused in standard mode")
    base = resolve_for(mode, **selectors)
    for extra in (
        {"required_input": frozenset({"image"})},
        {"required_input": frozenset({"image", "document"}), "provisional": True},
        {"provisional": True},
    ):
        assert resolve_for(mode, **selectors, **extra) == base


# --- nothing here names how a model is chosen ------------------------------------------------

# Spelled in pieces so this file does not contain the words it forbids elsewhere.
FORBIDDEN = ("rou" + "ter", "evi" + "dence", "held " + "model", "routing" + "-v2")


@pytest.mark.parametrize(
    "path",
    [Path(call_flow.__file__), Path(__file__)],
    ids=["call_flow.py", "test_call_flow.py"],
)
def test_the_scaffolding_and_its_test_name_none_of_the_forbidden_words(path):
    text = path.read_text().lower()
    assert [w for w in FORBIDDEN if w in text] == []

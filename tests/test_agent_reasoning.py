"""routing-v2 task 5.3: the request builder carries ``reasoning.effort`` for a model level the
router chose, and nothing else changes (spec ``agent-ask``: "A routed model call may carry a
reasoning effort"). No router exists yet, so every test passes the level directly."""

import re
from pathlib import Path

import pytest
from agent_support import make_world, respond_with
from chat_support import TOOL as CHAT

from mcp_perplexity_pro import agent
from mcp_perplexity_pro.agent import AskOptions, build_request
from mcp_perplexity_pro.matrix import LEVELS
from mcp_perplexity_pro.routing import Route

SRC = Path(agent.__file__).parent
MODEL = "openai/gpt-6-luna"


def model_route(model=MODEL):
    return Route("dynamic", "standard", model, None, "router")


def preset_route(preset="low"):
    return Route("standard", None, None, preset, "depth")


def build(route, **kwargs):
    return build_request(AskOptions(route=route), "q", store=False, **kwargs)


# --- the scenarios of the spec ----------------------------------------------------------------


def test_a_routed_model_with_a_level_names_the_model_and_the_reasoning_and_no_effort_key():
    body = build(model_route(), reasoning_effort="medium")
    assert body["model"] == MODEL and body["reasoning"] == {"effort": "medium"}
    assert "effort" not in body and "preset" not in body


def test_a_routed_model_with_no_level_has_no_reasoning_key():
    assert "reasoning" not in build(model_route())
    assert "reasoning" not in build(model_route(), reasoning_effort=None)


def test_an_explicit_or_configured_model_call_sends_no_reasoning():
    # the same builder, no level passed: how every explicit, configured and pinned call goes
    body = build(Route("standard", None, "perplexity/sonar", None, "default"))
    assert "reasoning" not in body and body["model"] == "perplexity/sonar"


def test_a_preset_call_sends_the_top_level_effort_and_no_reasoning():
    body = build(preset_route("low"))
    assert body["effort"] == "low" and "reasoning" not in body and "model" not in body


@pytest.mark.parametrize("level", LEVELS)
def test_every_matrix_level_is_carried_verbatim(level):
    assert build(model_route(), reasoning_effort=level)["reasoning"] == {"effort": level}


def test_the_level_sits_beside_the_model_shape_and_changes_nothing_else():
    plain = build(model_route())
    with_level = build(model_route(), reasoning_effort="low")
    assert {k: v for k, v in with_level.items() if k != "reasoning"} == plain
    assert plain["tools"] == [{"type": "web_search"}] and plain["max_steps"] == 3


def test_search_false_with_a_level_still_sends_reasoning_and_no_tools():
    options = AskOptions(route=model_route(), search=False)
    body = build_request(options, "q", store=False, reasoning_effort="low")
    assert body["reasoning"] == {"effort": "low"} and "tools" not in body


def test_an_anthropic_model_keeps_its_output_cap_with_a_level():
    body = build(model_route("anthropic/claude-haiku-5-5"), reasoning_effort="low")
    assert body["max_output_tokens"] == agent.ANTHROPIC_DEFAULT_CAP
    assert body["reasoning"] == {"effort": "low"}


@pytest.mark.parametrize("level", ["xl", "", "LOW", "none", 3])
def test_a_level_outside_the_matrix_vocabulary_is_a_caller_bug(level):
    with pytest.raises(ValueError):
        build(model_route(), reasoning_effort=level)


def test_a_level_on_a_preset_route_is_a_caller_bug():
    with pytest.raises(ValueError):
        build(preset_route(), reasoning_effort="low")


def test_the_option_validation_still_runs_first_for_a_bad_option():
    from mcp_perplexity_pro.errors import PerplexityError

    with pytest.raises(PerplexityError) as info:
        build_request(
            AskOptions(route=model_route(), domains=["x"], search=False),
            "q",
            store=False,
            reasoning_effort="low",
        )
    assert info.value.category == "invalid_request"


# --- nothing that exists today sends it, end to end -------------------------------------------


@pytest.fixture
async def world(make_settings):
    made = []

    async def build_world(**settings):
        w = await make_world(make_settings, respond_with("agent_fast_effort.json"), **settings)
        made.append(w)
        return w

    yield build_world
    for w in made:
        await w.aclose()


@pytest.mark.parametrize(
    "arguments",
    [{}, {"model": MODEL}, {"depth": "fast"}, {"tier": "light"}],
    ids=["nameless", "model", "depth", "tier"],
)
async def test_no_ask_in_any_mode_sends_reasoning_before_the_router_exists(world, arguments):
    for mode in ({}, {"routing": "dynamic"}):
        w = await world(**mode)
        result = await w.call("perplexity_ask", query="q", **arguments)
        if result.is_error:  # a named tier is refused in standard mode: nothing was sent
            assert not w.bodies()
            continue
        (body,) = w.bodies()
        assert "reasoning" not in body


async def test_a_chat_send_sends_no_reasoning_before_the_router_exists(world):
    w = await world(routing="dynamic")
    result = await w.call(CHAT, action="send", message="q", title="t")
    assert not result.is_error, result.content
    assert all("reasoning" not in body for body in w.bodies())


async def test_a_research_submit_is_untouched(world):
    w = await world()
    await w.call("perplexity_research", query="q")
    assert all("reasoning" not in body for body in w.bodies())


# --- no digest reads ``reasoning`` from a response (design D10: a request-side field only) -----

# A read of ``reasoning`` from any mapping (a ``.get(...)`` or a subscript). Writing the request
# (``body["reasoning"] = ...``) is not a read, and ``reasoning_tokens`` is a different key.
REASONING_READ = re.compile(
    r"\.get\(\s*[\"']reasoning[\"']|\[\s*[\"']reasoning[\"']\s*\](?!\s*=[^=])"
)


def reasoning_reads(root: Path) -> list[str]:
    return [
        f"{path.name}:{n}: {line.strip()}"
        for path in sorted(root.rglob("*.py"))
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if REASONING_READ.search(line)
    ]


def test_no_source_reads_reasoning_from_a_response():
    assert reasoning_reads(SRC) == []


def test_the_reasoning_read_check_sees_a_get_and_a_subscript_but_not_a_write(tmp_path):
    (tmp_path / "bad.py").write_text('a = run.get("reasoning")\nb = x["reasoning"]\n')
    (tmp_path / "ok.py").write_text(
        'body["reasoning"] = {"effort": level}\nrun.get("reasoning_tokens")\n'
    )
    assert [h.split(":")[0] for h in reasoning_reads(tmp_path)] == ["bad.py"] * 2

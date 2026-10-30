"""api-drift-2026-10 task 1.1: Agent requests name the preset as ``effort`` and never ``preset``,
and a response whose ``effort`` and ``preset`` are versioned (``fast@2026-10-16.0``, recorded in
``agent_fast_effort.json``) is read, stored and recorded as before (specs ``agent-ask``,
``agent-chat``, ``agent-research``)."""

import re
from pathlib import Path

import pytest
from agent_support import fixture, make_world, respond_with
from chat_support import TOOL as CHAT
from chat_support import sequence, variant

from mcp_perplexity_pro import agent
from mcp_perplexity_pro.agent import snapshot_model

ASK = "perplexity_ask"
RESEARCH = "perplexity_research"
EFFORT_FIXTURE = "agent_fast_effort.json"
SRC = Path(agent.__file__).parent


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder=None, **settings):
        w = await make_world(make_settings, responder or respond_with(EFFORT_FIXTURE), **settings)
        made.append(w)
        return w

    yield build
    for w in made:
        await w.aclose()


# --- the recorded response ---------------------------------------------------------------------


def test_the_recorded_response_carries_versioned_effort_and_preset_values():
    body = fixture(EFFORT_FIXTURE)
    meta = fixture("agent_fast_effort.meta.json")
    assert meta["request"]["effort"] == "fast" and "preset" not in meta["request"]
    assert re.fullmatch(r"fast@\d{4}-\d{2}-\d{2}\.\d+", body["effort"])
    assert body["preset"] == body["effort"] and body["status"] == "completed"


# --- the request -------------------------------------------------------------------------------


@pytest.mark.parametrize("depth", ["fast", "low", "medium"])
async def test_an_ask_at_a_depth_sends_effort_and_no_preset(world, depth):
    w = await world()
    result = await w.call(ASK, query="q", depth=depth)
    assert not result.is_error, result.content
    (body,) = w.bodies()
    assert body["effort"] == depth and "preset" not in body


async def test_an_ask_naming_a_model_sends_neither_field(world):
    w = await world()
    await w.call(ASK, query="q", model="perplexity/sonar")
    (body,) = w.bodies()
    assert "effort" not in body and "preset" not in body and body["model"] == "perplexity/sonar"


async def test_a_chat_send_at_a_depth_sends_effort_and_no_preset(world):
    w = await world()
    result = await w.call(CHAT, action="send", message="q", title="t", depth="fast")
    assert not result.is_error, result.content
    (body,) = w.bodies()
    assert body["effort"] == "fast" and "preset" not in body


async def test_a_research_submit_sends_its_depth_as_effort_and_no_preset(research_world):
    w = await research_world()
    result = await w.call(RESEARCH, query="q")
    assert not result.is_error, result.content
    (body,) = w.bodies()
    assert body["effort"] == "medium" and "preset" not in body
    assert body["background"] is True and body["store"] is True


# --- the versioned response ----------------------------------------------------------------------


async def test_a_versioned_response_is_digested_and_records_the_requested_preset(world):
    w = await world()
    result = await w.call(ASK, query="q", depth="fast")
    out = result.structured_content
    assert not result.is_error and out["depth"] == "fast" and out["answer"]
    (event,) = await w.events()
    assert event[2] == "ok" and event[3] == "fast"  # the request's name, not fast@2026-10-16.0
    assert event[3] != fixture(EFFORT_FIXTURE)["preset"]


async def test_a_versioned_chat_turn_stores_the_requested_preset_and_a_follow_up_recovers_tier(
    make_settings,
):
    first = fixture(EFFORT_FIXTURE)
    w = await make_world(
        make_settings,
        sequence(first, variant(EFFORT_FIXTURE, "resp_second-effort")),
        routing="dynamic",
    )
    try:
        r1 = await w.call(
            CHAT,
            action="send",
            title="t",
            message="Compare two designs and evaluate their trade-offs.",
        )
        assert not r1.is_error, r1.content
        assert r1.structured_content["routing"]["tier"] == "complex"
        stored = await w.rows("SELECT preset FROM chat_messages WHERE role = 'assistant'")
        assert stored == [("medium",)]  # the request's preset, not the response's version
        r2 = await w.call(CHAT, action="send", chat_id=1, message="and in 2025?")
        assert not r2.is_error, r2.content
        assert r2.structured_content["routing"]["tier"] == "complex"  # recovered from the store
        assert "held at complex" in r2.structured_content["routing"]["reason"]
        assert [b["effort"] for b in w.bodies()] == ["medium", "medium"]
    finally:
        await w.aclose()


# --- a research snapshot's model ---------------------------------------------------------------


@pytest.mark.parametrize("status", ["queued", "in_progress", "cancelled"])
def test_a_non_completed_snapshot_with_a_versioned_model_has_no_model(status):
    raw = {"status": status, "model": "medium@2026-10-16.0"}
    assert snapshot_model(raw, "medium") is None


def test_a_completed_snapshot_keeps_its_model_verbatim():
    raw = {"status": "completed", "model": "medium@2026-10-16.0"}
    assert snapshot_model(raw, "medium") == "medium@2026-10-16.0"
    raw = {"status": "completed", "model": "openai/gpt-6-luna"}
    assert snapshot_model(raw, "medium") == "openai/gpt-6-luna"


# --- no digest code reads the response's effort or preset ----------------------------------------


# A read of ``effort`` or ``preset`` from any mapping (a ``.get(...)`` or a subscript). A write
# that builds the request (``request["effort"] = ...``) is not a read.
EFFORT_READ = re.compile(
    r"\.get\(\s*[\"'](?:effort|preset)[\"']|\[\s*[\"'](?:effort|preset)[\"']\s*\](?!\s*=[^=])"
)


def effort_reads(root: Path) -> list[str]:
    return [
        f"{path.name}:{n}: {line.strip()}"
        for path in sorted(root.rglob("*.py"))
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if EFFORT_READ.search(line)
    ]


def test_no_source_reads_effort_or_preset_from_a_response():
    assert effort_reads(SRC) == []


def test_the_effort_read_check_sees_a_get_and_a_subscript_but_not_a_request_write(tmp_path):
    (tmp_path / "bad.py").write_text(
        'a = data.get("preset")\nb = x["effort"]\nc = y.get( "effort", None)\n'
    )
    (tmp_path / "ok.py").write_text('request["effort"] = options.preset\n')
    assert [h.split(":")[0] for h in effort_reads(tmp_path)] == ["bad.py"] * 3

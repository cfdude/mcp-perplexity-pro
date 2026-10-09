"""Task 3.6: the live continuation check of design D6, and the offline tests of what it saved.

The live test (``-m live``, a real key in the environment, never stored in the repo) sends three
chained turns through ``perplexity_chat`` at the cheapest depths, then one replay turn::

    PERPLEXITY_API_KEY=... uv run pytest -m live tests/test_agent_live.py -s

Turn 1 (``fast``) states a codeword, turn 2 (``low``, the depth switch no earlier capture covers)
adds a fact, turn 3 (``fast``) asks for the codeword, and the replay turn asks for both facts on
the same chat. Expected cost about $0.012 in total; the run aborts before any call once the
measured spend reaches $0.02. No depth above ``low`` is ever sent.

The replay request and response and the depth-switch turn are SAVED as scrubbed fixtures
(``agent_chat_replay`` and ``agent_chat_depth_switch``, each with a sidecar whose ``request`` is
the body sent; request headers and the key are never recorded). The offline tests at the bottom
prove the tool builds exactly the saved requests.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest
from agent_support import fixture
from chat_support import TOOL, sequence
from fastmcp import Client
from fixture_support import FIXTURE_DIR, find_key_shapes
from sqlalchemy import text
from test_live_capture import scrub

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.settings import Settings
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

COST_STOP = Decimal("0.02")
ALLOWED_PRESETS = ("fast", "low")  # never anything deeper in this test
CODEWORD = "PELICAN-42"
COLOUR = "teal"
PROMPTS = {
    "turn1": f"Remember this for later: my codeword is {CODEWORD}. Just reply OK.",
    "turn2": f"Also remember: my favourite colour is {COLOUR}. Just reply OK.",
    "turn3": "What is my codeword? Reply with the codeword only.",
    "replay": "What is my favourite colour and what is my codeword? One short sentence.",
}
REPLAY_FIXTURE = "agent_chat_replay"
DEPTH_SWITCH_FIXTURE = "agent_chat_depth_switch"


@dataclass
class Turn:
    name: str
    depth: str
    arguments: dict[str, Any]
    error: str | None = None
    answer: str = ""
    cost: Decimal = Decimal(0)
    latency_ms: int | None = None
    response_id: str | None = None
    previous_response_id: str | None = None
    http_status: int | None = None
    request: dict[str, Any] | None = None
    response: Any = None


@dataclass
class Evidence:
    turns: dict[str, Turn] = field(default_factory=dict)
    spent: Decimal = Decimal(0)

    def report(self) -> str:
        lines = ["LIVE CONTINUATION CHECK"]
        for t in self.turns.values():
            outcome = f"ERROR {t.error}" if t.error else f"ok answer={t.answer!r}"
            lines.append(
                f"  {t.name:7} depth={t.depth:4} http={t.http_status} cost=${t.cost} "
                f"latency={t.latency_ms}ms prev={t.previous_response_id} id={t.response_id} "
                f"{outcome}"
            )
        lines.append(f"  total spent ${self.spent} (hard stop ${COST_STOP})")
        return "\n".join(lines)


class Recorder:
    """httpx2 event hooks that keep the body sent and the body received of every call, and
    nothing else: never a header, so the key cannot reach a fixture."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def on_request(self, request: httpx2.Request) -> None:
        await request.aread()
        self.calls.append({"request": json.loads(request.content), "response": None})

    async def on_response(self, response: httpx2.Response) -> None:
        await response.aread()
        self.calls[-1]["status"] = response.status_code
        self.calls[-1]["content_type"] = response.headers.get("content-type")
        try:
            self.calls[-1]["response"] = response.json()
        except ValueError:
            self.calls[-1]["response"] = {"_non_json_body": response.text}

    def client(self, transport: httpx2.AsyncBaseTransport | None = None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=transport,
            event_hooks={"request": [self.on_request], "response": [self.on_response]},
        )


async def run_live_check(settings: Settings, http: httpx2.AsyncClient, rec: Recorder) -> Evidence:
    """Three chained turns and a replay turn through ``perplexity_chat``, built as in production."""
    engine = create_engine_for(settings)
    server = build_server(settings, http, engine)
    evidence = Evidence()
    chat_id: int | None = None
    plan = [
        ("turn1", "fast", {"title": "Live continuation check"}),
        ("turn2", "low", {}),
        ("turn3", "fast", {}),
        ("replay", "fast", {"replay": True}),
    ]
    try:
        async with Client(server) as client:
            for name, depth, extra in plan:
                assert depth in ALLOWED_PRESETS
                if evidence.spent >= COST_STOP:
                    pytest.fail(f"hard stop: ${evidence.spent} spent before {name}")
                arguments = {
                    "action": "send",
                    "message": PROMPTS[name],
                    "depth": depth,
                    "project": "live-check",
                    **extra,
                }
                if chat_id is not None:
                    arguments["chat_id"] = chat_id
                turn = Turn(name=name, depth=depth, arguments=arguments)
                evidence.turns[name] = turn
                before = len(rec.calls)
                result = await client.call_tool(TOOL, arguments, raise_on_error=False)
                if len(rec.calls) > before:  # a request left; keep what was sent and received
                    call = rec.calls[-1]
                    turn.request, turn.response = call["request"], call["response"]
                    turn.http_status = call.get("status")
                    turn.previous_response_id = call["request"].get("previous_response_id")
                    assert call["request"].get("preset") in ALLOWED_PRESETS, call["request"]
                if result.is_error:
                    turn.error = str(result.structured_content)
                    break  # a failed turn ends the conversation; the evidence is what it is
                out = result.structured_content
                turn.answer = out["answer"] or ""
                turn.response_id = out["response_id"]
                turn.latency_ms = out["latency_ms"]
                cost = out["usage"]["cost_usd"]
                turn.cost = Decimal(cost) if cost is not None else Decimal(0)
                evidence.spent += turn.cost
                chat_id = out["chat_id"]
    finally:
        await engine.dispose()
    return evidence


def save_fixture(name: str, turn: Turn, note: str, directory: Path, key: str) -> None:
    """Scrub, key-scan and write one payload with its sidecar (nothing is written on a hit)."""
    removed: list[str] = []
    payload = scrub(turn.response, "", removed)
    meta = {
        "endpoint": "/v1/agent",
        "method": "POST",
        "http_status": turn.http_status,
        "capture_date": date.today().isoformat(),
        "content_type": "application/json",
        "scrubbed": removed or "nothing: no account-specific values were present",
        "note": "Response ids are kept; they identify no account. Request headers and the API "
        "key are never recorded.",
        "request_note": note,
        "request": turn.request,
    }
    body, sidecar = json.dumps(payload, indent=2) + "\n", json.dumps(meta, indent=2) + "\n"
    assert not find_key_shapes(body + sidecar), f"key-shaped string in {name}; nothing written"
    assert key not in body + sidecar, f"the live key is in {name}; nothing written"
    directory.mkdir(exist_ok=True)
    (directory / f"{name}.json").write_text(body)
    (directory / f"{name}.meta.json").write_text(sidecar)


def save_evidence(evidence: Evidence, directory: Path, key: str) -> None:
    switch, replay = evidence.turns.get("turn2"), evidence.turns.get("replay")
    if switch is not None and switch.request is not None:
        save_fixture(
            DEPTH_SWITCH_FIXTURE,
            switch,
            "chat turn 2: depth low chained from a fast turn's store:false response",
            directory,
            key,
        )
    if replay is not None and replay.request is not None:
        save_fixture(
            REPLAY_FIXTURE,
            replay,
            "chat replay: the stored history of three turns resent as message items, "
            "store false, no previous_response_id",
            directory,
            key,
        )


@pytest.mark.live
@pytest.mark.allow_network
async def test_live_three_chained_turns_a_depth_switch_and_a_replay(tmp_path):
    key = os.environ.get("PERPLEXITY_API_KEY")
    if not key:
        pytest.skip("PERPLEXITY_API_KEY is not set")
    settings = Settings(api_key=key, data_dir=tmp_path / "data")
    migrate(settings)
    rec = Recorder()
    http = rec.client()
    try:
        evidence = await run_live_check(settings, http, rec)
    finally:
        await http.aclose()
    print("\n" + evidence.report())
    save_evidence(evidence, FIXTURE_DIR, key)  # saved before any assertion: failures are evidence
    assert evidence.spent < COST_STOP
    turns = evidence.turns
    assert turns["turn2"].error is None, "the depth switch (fast then low) was rejected"
    assert turns["turn3"].error is None, "a store:false anchor was rejected at level 3"
    assert CODEWORD in turns["turn3"].answer, "the chain lost the codeword at turn 3"
    assert turns["replay"].error is None, "the replay request was rejected"
    assert CODEWORD in turns["replay"].answer and COLOUR in turns["replay"].answer.lower()


# --- offline: what the live run saved ---------------------------------------------------------


async def seed_history(w, items: list[dict[str, str]]) -> int:
    """A chat holding ``items`` (alternating user and assistant) exactly as given."""
    async with w.engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO projects (name) VALUES ('default') ON CONFLICT (name) DO NOTHING")
        )
        pid = (await conn.execute(text("SELECT id FROM projects WHERE name='default'"))).scalar()
        stamp = "2026-10-09 12:00:00.000000"
        await conn.execute(
            text(
                "INSERT INTO chats (project_id, title, created_at, updated_at) "
                "VALUES (:p, 'seeded', :t, :t)"
            ),
            {"p": pid, "t": stamp},
        )
        chat = (await conn.execute(text("SELECT max(id) FROM chats"))).scalar()
        for n, item in enumerate(items):
            await conn.execute(
                text(
                    "INSERT INTO chat_messages (chat_id, role, content, created_at, response_id) "
                    "VALUES (:c, :r, :x, :t, :rid)"
                ),
                {
                    "c": chat,
                    "r": item["role"],
                    "x": item["content"],
                    "t": stamp,
                    "rid": f"resp_seed{n}" if item["role"] == "assistant" else None,
                },
            )
    return chat


async def test_the_built_replay_request_equals_the_saved_sidecar_request(chat_world):
    meta = fixture(f"{REPLAY_FIXTURE}.meta.json")
    request = meta["request"]
    history, new = request["input"][:-1], request["input"][-1]
    assert new["role"] == "user" and len(history) % 2 == 0 and len(history) >= 4
    w = await chat_world(sequence(f"{REPLAY_FIXTURE}.json"))
    chat = await seed_history(w, history)
    result = await w.call(
        TOOL,
        action="send",
        chat_id=chat,
        message=new["content"],
        replay=True,
        depth=request["preset"],
    )
    assert not result.is_error, result.content
    assert w.bodies() == [request]  # the shape the live API accepted, byte for byte
    assert result.structured_content["answer"]  # the recorded replay response digests


async def test_the_built_depth_switch_request_equals_the_saved_sidecar_request(chat_world):
    meta = fixture(f"{DEPTH_SWITCH_FIXTURE}.meta.json")
    request = meta["request"]
    assert request["preset"] == "low" and request["store"] is False
    w = await chat_world(sequence(f"{DEPTH_SWITCH_FIXTURE}.json", status=meta["http_status"]))
    chat = await seed_history(
        w,
        [
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": "earlier answer"},
        ],
    )
    async with w.engine.begin() as conn:  # the anchor the live run chained from
        await conn.execute(
            text("UPDATE chat_messages SET response_id = :r WHERE role = 'assistant'"),
            {"r": request["previous_response_id"]},
        )
    await w.call(TOOL, action="send", chat_id=chat, message=request["input"], depth="low")
    assert w.bodies() == [request]


def test_the_saved_fixtures_are_scrubbed_and_never_hold_a_header_or_a_key():
    for name in (REPLAY_FIXTURE, DEPTH_SWITCH_FIXTURE):
        raw = (FIXTURE_DIR / f"{name}.json").read_text() + (
            FIXTURE_DIR / f"{name}.meta.json"
        ).read_text()
        assert not find_key_shapes(raw)
        assert "authorization" not in raw.lower() and "bearer" not in raw.lower()

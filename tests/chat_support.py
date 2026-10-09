"""Helpers for the chat tool tests: a world builder, a sequence responder over recorded
fixtures, and the direct-SQL reads the assertions use."""

import copy
from typing import Any

import httpx2
import pytest
from agent_support import World, fixture, make_world

TOOL = "perplexity_chat"
TURN_A = "agent_chat_turn_a.json"
TURN_B = "agent_chat_turn_b.json"
A_ID = fixture(TURN_A)["id"]
B_ID = fixture(TURN_B)["id"]
FIRST = fixture("agent_chat_turn_a.meta.json")["request"]["input"]
FOLLOW_UP = fixture("agent_chat_turn_b.meta.json")["request"]["input"]


def variant(name: str, response_id: str) -> dict[str, Any]:
    """A recorded response served again under another id (a third turn needs its own id)."""
    body = copy.deepcopy(fixture(name))
    body["id"] = response_id
    return body


def sequence(*bodies: Any, status: int = 200):
    """Serve ``bodies`` in call order (a name loads the fixture); the last one repeats."""

    def responder(request, n):
        item = bodies[min(n, len(bodies)) - 1]
        body = fixture(item) if isinstance(item, str) else item
        return httpx2.Response(status, json=body)

    return responder


def category(result) -> str:
    assert result.is_error
    return result.structured_content["category"]


def message(result) -> str:
    return result.structured_content["message"]


@pytest.fixture
async def chat_world(make_settings):
    made: list[World] = []

    async def build(responder=None, **settings):
        w = await make_world(make_settings, responder or sequence(TURN_A, TURN_B), **settings)
        made.append(w)
        return w

    yield build
    for w in made:
        await w.aclose()


async def nothing_happened(w: World, *, chats: int = 0) -> None:
    """No request reached the API and no usage event, project or (extra) chat appeared."""
    assert w.requests == []
    assert await w.count("usage_events") == 0
    assert await w.count("chats") == chats


async def messages_of(w: World, chat_id: int) -> list[tuple]:
    return await w.rows(
        "SELECT role, content, response_id FROM chat_messages WHERE chat_id = :c ORDER BY id",
        c=chat_id,
    )


async def seed_chat(w: World, project: str, title: str, turns: int = 2, *, tag: str = "") -> int:
    """A chat with ``turns`` completed turns, written straight to storage (no upstream call, no
    usage event); the assistant of turn ``n`` has response id ``resp_<tag><n>``."""
    from mcp_perplexity_pro.storage.chats import AssistantTurn, append_turn, create_chat
    from mcp_perplexity_pro.storage.projects import get_or_create_project
    from mcp_perplexity_pro.storage.session import unit_of_work

    async with unit_of_work(w.engine) as session:
        pid = (await get_or_create_project(session, project)).id
        first = AssistantTurn(f"resp_{tag}1", f"answer {tag}1", "openai/gpt-6-luna", "fast", "[]")
        chat = await create_chat(session, pid, title, f"question {tag}1", first)
        for n in range(2, turns + 1):
            turn = AssistantTurn(f"resp_{tag}{n}", f"answer {tag}{n}", "openai/gpt-6-luna", "fast")
            await append_turn(session, pid, chat.id, f"question {tag}{n}", turn)
    return chat.id

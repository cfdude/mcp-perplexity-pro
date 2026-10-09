"""Task 3.5: ``perplexity_chat`` actions ``list``, ``read`` and ``delete`` (agent-chat "Listing
chats", "Reading a chat", "Deleting a chat", "Actions that store nothing never create a
project")."""

import jsonschema
import pytest
from chat_support import (
    FIRST,
    TOOL,
    category,
    message,
    seed_chat,
    sequence,
)
from fastmcp import Client
from sqlalchemy import text


async def quiet(w):
    """No request reached the API and no usage event was written."""
    assert w.requests == []
    assert await w.count("usage_events") == 0


async def test_the_listing_has_the_annotations_costs_and_wording_of_every_action(chat_world):
    w = await chat_world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    ann = tool.annotations
    assert (ann.read_only_hint, ann.destructive_hint, ann.open_world_hint) == (False, True, True)
    assert (
        tool.output_schema["properties"]["chat_id"] and "chats" in tool.output_schema["properties"]
    )
    desc = " ".join(tool.description.split())
    for cost in ("$0.001 to $0.002", "$0.004 to $0.02", "$0.016 to $0.05"):
        assert cost in desc
    assert "list, read and delete make no upstream call" in desc
    assert "local database" in desc and "only hides" in desc and "retrieval" in desc
    lowered = desc.lower()
    for claim in (
        "nothing is retained",
        "not retained",
        "no retention",
        "keeps nothing",
        "never stored",
        "deletes",
        "private",
    ):
        assert claim not in lowered, claim
    for name in ("action", "message", "title", "chat_id", "project", "replay", "limit", "confirm"):
        assert name in tool.input_schema["properties"]
    assert "confirm" in tool.input_schema["properties"]
    assert tool.input_schema["required"] == ["action"]


async def test_an_unknown_action_fails_naming_action(chat_world):
    w = await chat_world()
    result = await w.call(TOOL, action="rename", chat_id=1)
    assert category(result) == "invalid_request" and "action" in message(result)
    await quiet(w)


# --- list ------------------------------------------------------------------------------------


async def test_list_is_newest_updated_first_and_the_top_level_chat_id_is_null(chat_world):
    w = await chat_world()
    first = await seed_chat(w, "default", "first", tag="a")
    second = await seed_chat(w, "default", "second", tag="b")
    out = (await w.call(TOOL, action="list")).structured_content
    assert [c["id"] for c in out["chats"]] == [second, first]
    assert out["chat_id"] is None and out["action"] == "list" and out["project"] == "default"
    assert (out["chats_total"], out["truncated"]) == (2, False)
    assert [(c["title"], c["message_count"]) for c in out["chats"]] == [("second", 4), ("first", 4)]
    # the older chat receives a new message: it moves to the front
    await w.call(TOOL, action="send", chat_id=first, message="more")
    out = (await w.call(TOOL, action="list")).structured_content
    assert [c["id"] for c in out["chats"]] == [first, second]


async def test_list_limit_reports_the_total_and_truncation(chat_world):
    w = await chat_world()
    ids = [await seed_chat(w, "p", f"chat {n}", tag=str(n)) for n in range(3)]
    out = (await w.call(TOOL, action="list", project="p", limit=2)).structured_content
    assert [c["id"] for c in out["chats"]] == [ids[2], ids[1]]
    assert (out["chats_total"], out["truncated"]) == (3, True)
    exact = (await w.call(TOOL, action="list", project="p", limit=3)).structured_content
    assert (len(exact["chats"]), exact["truncated"]) == (3, False)


async def test_list_in_an_absent_project_is_empty_and_creates_nothing(chat_world):
    w = await chat_world()
    out = (await w.call(TOOL, action="list", project="ghost")).structured_content
    assert (out["chats"], out["chats_total"], out["truncated"]) == ([], 0, False)
    assert await w.count("projects") == 0
    default = (await w.call(TOOL, action="list")).structured_content  # fresh install
    assert default["chats_total"] == 0 and await w.count("projects") == 0
    await quiet(w)


async def test_list_only_shows_its_own_project(chat_world):
    w = await chat_world()
    await seed_chat(w, "a", "mine", tag="a")
    await seed_chat(w, "b", "theirs", tag="b")
    out = (await w.call(TOOL, action="list", project="a")).structured_content
    assert [c["title"] for c in out["chats"]] == ["mine"]


@pytest.mark.parametrize(
    ("action", "limit"), [("list", 0), ("list", 101), ("read", 0), ("read", 201)]
)
async def test_a_limit_out_of_range_fails_naming_limit(chat_world, action, limit):
    w = await chat_world()
    chat = await seed_chat(w, "default", "t")
    result = await w.call(TOOL, action=action, chat_id=chat, limit=limit)
    assert category(result) == "invalid_request" and "limit" in message(result)


# --- read ------------------------------------------------------------------------------------


async def test_read_returns_the_messages_in_order_without_an_upstream_call(chat_world):
    w = await chat_world()
    chat = await seed_chat(w, "default", "t", turns=2)
    out = (await w.call(TOOL, action="read", chat_id=chat)).structured_content
    assert [(m["role"], m["content"]) for m in out["messages"]] == [
        ("user", "question 1"),
        ("assistant", "answer 1"),
        ("user", "question 2"),
        ("assistant", "answer 2"),
    ]
    assert out["chat_id"] == chat and out["chat"]["id"] == chat and out["chat"]["title"] == "t"
    assert (out["messages_total"], out["truncated"]) == (4, False)
    assert out["messages"][1]["response_id"] == "resp_1"
    assert out["messages"][1]["model"] == "openai/gpt-6-luna"
    await quiet(w)


async def test_read_with_a_limit_returns_the_last_n_in_order(chat_world):
    w = await chat_world()
    chat = await seed_chat(w, "default", "t", turns=2)
    out = (await w.call(TOOL, action="read", chat_id=chat, limit=3)).structured_content
    assert [m["content"] for m in out["messages"]] == ["answer 1", "question 2", "answer 2"]
    assert (out["messages_total"], out["truncated"]) == (4, True)


async def test_read_returns_a_stored_sources_list_and_survives_a_damaged_one(chat_world):
    w = await chat_world()
    chat = await seed_chat(w, "default", "t", turns=1)
    async with w.engine.begin() as conn:
        await conn.execute(
            text("UPDATE chat_messages SET sources_json = :s WHERE role = 'assistant'"),
            {"s": '[{"url": "https://a.example", "title": "A"}]'},
        )
    out = (await w.call(TOOL, action="read", chat_id=chat)).structured_content
    assert out["messages"][1]["sources"] == [
        {"url": "https://a.example", "title": "A", "date": None, "id": None}
    ]
    async with w.engine.begin() as conn:
        await conn.execute(text("UPDATE chat_messages SET sources_json = 'not json'"))
    again = await w.call(TOOL, action="read", chat_id=chat)
    assert not again.is_error and again.structured_content["messages"][1]["sources"] == []


async def test_read_and_delete_in_an_absent_project_are_not_found_and_create_nothing(chat_world):
    w = await chat_world()
    read = await w.call(TOOL, action="read", chat_id=1, project="ghost")
    delete = await w.call(TOOL, action="delete", chat_id=1, project="ghost", confirm=True)
    assert category(read) == category(delete) == "not_found"
    assert await w.count("projects") == 0
    await quiet(w)


async def test_a_chat_of_another_project_is_not_found_for_read_and_delete(chat_world):
    w = await chat_world()
    chat = await seed_chat(w, "a", "mine")
    await seed_chat(w, "b", "other")
    read = await w.call(TOOL, action="read", chat_id=chat, project="b")
    delete = await w.call(TOOL, action="delete", chat_id=chat, project="b", confirm=True)
    assert category(read) == category(delete) == "not_found"
    assert await w.count("chats") == 2 and await w.count("chat_messages") == 8


async def test_read_and_delete_need_a_chat_id(chat_world):
    w = await chat_world()
    for action in ("read", "delete"):
        result = await w.call(TOOL, action=action, confirm=True)
        assert category(result) == "invalid_request" and "chat_id" in message(result)


# --- delete ----------------------------------------------------------------------------------


async def test_delete_without_confirm_fails_and_the_chat_remains(chat_world):
    w = await chat_world()
    chat = await seed_chat(w, "default", "t")
    for arguments in ({}, {"confirm": False}):
        result = await w.call(TOOL, action="delete", chat_id=chat, **arguments)
        assert category(result) == "confirmation_required"
    assert await w.count("chats") == 1 and await w.count("chat_messages") == 4


async def test_a_confirmed_delete_removes_the_chat_and_reports_the_messages(chat_world):
    w = await chat_world()
    chat = await seed_chat(w, "default", "t")
    keep = await seed_chat(w, "default", "keep", tag="k")
    out = (await w.call(TOOL, action="delete", chat_id=chat, confirm=True)).structured_content
    assert (out["action"], out["chat_id"], out["messages_removed"]) == ("delete", chat, 4)
    assert await w.rows("SELECT id FROM chats") == [(keep,)]
    assert await w.count("chat_messages") == 4  # only the kept chat's
    again = await w.call(TOOL, action="delete", chat_id=chat, confirm=True)
    assert category(again) == "not_found"
    await quiet(w)


async def test_a_deleted_newest_chats_id_is_never_reused(chat_world):
    w = await chat_world(sequence("agent_chat_turn_a.json"))
    await seed_chat(w, "default", "one", tag="a")
    newest = await seed_chat(w, "default", "two", tag="b")
    await w.call(TOOL, action="delete", chat_id=newest, confirm=True)
    fresh = (await w.call(TOOL, action="send", message=FIRST, title="fresh")).structured_content[
        "chat_id"
    ]
    assert fresh != newest
    stale = await w.call(TOOL, action="send", chat_id=newest, message="q")
    assert category(stale) == "not_found"
    assert await w.count("chat_messages") == 4 + 2  # the stale send appended nothing
    assert len(w.requests) == 1  # and never reached the API


# --- schema ----------------------------------------------------------------------------------


async def test_the_structured_content_of_every_action_validates_against_the_schema(chat_world):
    w = await chat_world(sequence("agent_chat_turn_a.json"))
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
        sent = await client.call_tool(TOOL, {"action": "send", "message": FIRST, "title": "t"})
        chat = sent.structured_content["chat_id"]
        calls = [
            sent,
            await client.call_tool(TOOL, {"action": "list"}),
            await client.call_tool(TOOL, {"action": "read", "chat_id": chat}),
            await client.call_tool(TOOL, {"action": "delete", "chat_id": chat, "confirm": True}),
        ]
    for result in calls:
        jsonschema.validate(result.structured_content, tool.output_schema)

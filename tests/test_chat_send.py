"""Task 3.3: ``perplexity_chat`` action ``send`` through ``build_server`` with a
request-capturing transport (agent-chat "Send starts a chat", "Send continues a chat", "Send takes
the ask options", "Replay of stored history")."""

import pytest
from agent_support import inline
from chat_support import (
    A_ID,
    B_ID,
    FIRST,
    FOLLOW_UP,
    TOOL,
    TURN_A,
    TURN_B,
    category,
    message,
    messages_of,
    nothing_happened,
    sequence,
    variant,
)
from fastmcp import Client
from sqlalchemy import text

THIRD_ID = "resp_third-turn"
TEAL = {"message": FIRST, "title": "Teal notes"}


async def first_turn(w, **extra):
    result = await w.call(TOOL, action="send", **{**TEAL, **extra})
    assert not result.is_error, result.content
    return result.structured_content


# --- listing ---------------------------------------------------------------------------------


async def test_the_listing_has_schema_annotations_and_the_honest_storage_wording(chat_world):
    w = await chat_world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    assert tool.output_schema and "chat_id" in tool.output_schema["properties"]
    ann = tool.annotations
    assert (ann.read_only_hint, ann.destructive_hint, ann.open_world_hint) == (False, True, True)
    desc = " ".join(tool.description.split())
    assert "local database" in desc and "only hides" in desc and "retrieval" in desc
    lowered = desc.lower()
    for claim in (
        "nothing is retained",
        "not retained",
        "no retention",
        "keeps nothing",
        "private",
    ):
        assert claim not in lowered, claim
    assert tool.input_schema["required"] == ["action"]
    assert "json_schema" not in tool.input_schema["properties"]


# --- the first turn --------------------------------------------------------------------------


async def test_a_first_turn_creates_the_chat_with_both_messages(chat_world):
    w = await chat_world()
    out = await first_turn(w)
    assert out["chat_id"] == 1 and out["continuation"] == "new" and out["action"] == "send"
    assert out["chat"]["title"] == "Teal notes" and out["chat"]["message_count"] == 2
    assert (out["answer"], out["status"], out["depth"]) == ("OK", "completed", "fast")
    assert out["response_id"] == A_ID and out["project"] == "default"
    assert await w.rows("SELECT id, title FROM chats") == [(1, "Teal notes")]
    assert await messages_of(w, 1) == [("user", FIRST, None), ("assistant", "OK", A_ID)]
    (event,) = await w.events()
    assert event[:3] == (TOOL, "agent", "ok")


async def test_the_first_turn_request_has_preset_fast_string_input_and_store_false(chat_world):
    w = await chat_world()
    await first_turn(w)
    assert w.bodies() == [{"preset": "fast", "input": FIRST, "store": False}]


async def test_a_title_is_trimmed_and_120_characters_is_accepted(chat_world):
    w = await chat_world()
    await first_turn(w, title=f"  {'t' * 120}  ")
    assert await w.rows("SELECT title FROM chats") == [("t" * 120,)]


@pytest.mark.parametrize(
    "arguments",
    [{"title": None}, {"title": "   "}, {"title": "x" * 121}],
    ids=["none", "blank", "long"],
)
async def test_a_missing_blank_or_long_title_fails_before_any_request(chat_world, arguments):
    w = await chat_world()
    result = await w.call(TOOL, action="send", message="hi", **arguments)
    assert category(result) == "invalid_request" and "title" in message(result)
    await nothing_happened(w)


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
async def test_a_blank_message_fails_with_and_without_a_chat(chat_world, text):
    w = await chat_world()
    await first_turn(w)
    requests, events = len(w.requests), await w.count("usage_events")
    for arguments in ({"title": "t"}, {"chat_id": 1}):
        result = await w.call(TOOL, action="send", message=text, **arguments)
        assert category(result) == "invalid_request" and "message" in message(result)
    assert (len(w.requests), await w.count("usage_events")) == (requests, events)
    assert await w.count("chat_messages") == 2


async def test_a_message_of_20001_characters_fails_and_20000_is_sent(chat_world):
    w = await chat_world()
    result = await w.call(TOOL, action="send", message="x" * 20001, title="t")
    assert category(result) == "invalid_request" and "message" in message(result)
    await nothing_happened(w)
    assert not (await w.call(TOOL, action="send", message="x" * 20000, title="t")).is_error
    assert w.bodies()[0]["input"] == "x" * 20000


async def test_a_failed_first_turn_leaves_no_chat(chat_world):
    w = await chat_world(sequence(inline("failed", error={"message": "boom"})))
    result = await w.call(TOOL, action="send", **TEAL)
    assert category(result) == "unexpected_response"
    assert await w.count("chats") == 0 and await w.count("chat_messages") == 0


# --- chaining --------------------------------------------------------------------------------


async def test_the_second_turn_chains_from_the_first_response(chat_world):
    w = await chat_world()
    await first_turn(w)
    result = await w.call(TOOL, action="send", chat_id=1, message=FOLLOW_UP)
    out = result.structured_content
    assert out["continuation"] == "chained" and out["chat_id"] == 1
    assert w.bodies()[1] == {
        "preset": "fast",
        "input": FOLLOW_UP,
        "previous_response_id": A_ID,
        "store": False,
    }
    assert out["response_id"] == B_ID and "PELICAN-42" in out["answer"]
    assert out["chat"]["message_count"] == 4
    assert await messages_of(w, 1) == [
        ("user", FIRST, None),
        ("assistant", "OK", A_ID),
        ("user", FOLLOW_UP, None),
        ("assistant", out["answer"], B_ID),
    ]
    events = await w.events()
    assert [(e[2], e[5]) for e in events] == [("ok", A_ID), ("ok", B_ID)]


async def test_the_third_turn_chains_from_the_second_response(chat_world):
    w = await chat_world(sequence(TURN_A, TURN_B, variant(TURN_B, THIRD_ID)))
    await first_turn(w)
    await w.call(TOOL, action="send", chat_id=1, message="and?")
    await w.call(TOOL, action="send", chat_id=1, message="once more")
    assert [b.get("previous_response_id") for b in w.bodies()] == [None, A_ID, B_ID]
    assert (await w.events())[-1][5] == THIRD_ID


async def test_a_different_depth_on_a_chained_turn_names_that_preset(chat_world):
    w = await chat_world()
    await first_turn(w)
    out = (
        await w.call(TOOL, action="send", chat_id=1, message="q", depth="low")
    ).structured_content
    assert w.bodies()[1]["preset"] == "low" and w.bodies()[1]["previous_response_id"] == A_ID
    assert out["depth"] == "low"
    assert (await w.rows("SELECT preset FROM chat_messages WHERE role='assistant' ORDER BY id"))[
        -1
    ] == ("low",)


async def test_the_ask_options_apply_and_json_schema_is_refused(chat_world):
    w = await chat_world()
    await first_turn(w, domains=["python.org"], instructions="Be brief.", max_output_tokens=300)
    body = w.bodies()[0]
    assert body["tools"][0]["filters"]["search_domain_filter"] == ["python.org"]
    assert (body["instructions"], body["max_output_tokens"]) == ("Be brief.", 300)
    bad = await w.call(TOOL, action="send", message="q", title="t", json_schema={"type": "object"})
    assert category(bad) == "invalid_request" and "json_schema" in message(bad)
    for arguments in ({"depth": "high"}, {"depth": "xhigh"}, {"domains": ["a.com", "-b.com"]}):
        bad = await w.call(TOOL, action="send", message="q", title="t", **arguments)
        assert category(bad) == "invalid_request"
    assert len(w.requests) == 1  # only the good first turn reached the API


async def test_a_title_with_a_chat_id_fails_before_any_request(chat_world):
    w = await chat_world()
    await first_turn(w)
    sent = len(w.requests)
    result = await w.call(TOOL, action="send", chat_id=1, message="q", title="rename")
    assert category(result) == "invalid_request" and "title" in message(result)
    assert len(w.requests) == sent


async def test_an_unknown_chat_and_another_projects_chat_are_not_found(chat_world):
    w = await chat_world()
    await first_turn(w, project="a")
    sent, events = len(w.requests), await w.count("usage_events")
    unknown = await w.call(TOOL, action="send", chat_id=999, message="q", project="a")
    other = await w.call(TOOL, action="send", chat_id=1, message="q", project="b")
    assert category(unknown) == category(other) == "not_found"
    assert (len(w.requests), await w.count("usage_events")) == (sent, events)
    assert await w.rows("SELECT name FROM projects") == [("a",)]  # b was never created


async def test_a_send_naming_an_absent_project_is_not_found_and_creates_nothing(chat_world):
    w = await chat_world()
    result = await w.call(TOOL, action="send", chat_id=1, message="q", project="ghost")
    assert category(result) == "not_found" and "ghost" in message(result)
    await nothing_happened(w)
    assert await w.count("projects") == 0


async def test_an_invalid_project_name_fails_before_anything(chat_world):
    w = await chat_world()
    for arguments in ({"title": "t"}, {"chat_id": 1}):
        result = await w.call(TOOL, action="send", message="q", project="bad name!", **arguments)
        assert category(result) == "invalid_request" and "project" in message(result)
    await nothing_happened(w)


# --- replay ----------------------------------------------------------------------------------


async def test_replay_resends_the_stored_history_as_message_items(chat_world):
    w = await chat_world()
    await first_turn(w)
    out = (
        await w.call(TOOL, action="send", chat_id=1, message=FOLLOW_UP, replay=True)
    ).structured_content
    body = w.bodies()[1]
    assert "previous_response_id" not in body and body["store"] is False
    assert body["input"] == [
        {"type": "message", "role": "user", "content": FIRST},
        {"type": "message", "role": "assistant", "content": "OK"},
        {"type": "message", "role": "user", "content": FOLLOW_UP},
    ]
    assert out["continuation"] == "replay" and out["chat"]["message_count"] == 4
    assert out["warnings"] == []


async def test_a_replay_over_100000_stored_characters_still_sends_and_warns_with_the_size(
    chat_world,
):
    w = await chat_world()
    await first_turn(w)
    big = "z" * 100_001
    async with w.engine.begin() as conn:  # write the oversize history directly
        await conn.execute(
            text("UPDATE chat_messages SET content = :c WHERE role='assistant'"), {"c": big}
        )
    out = (
        await w.call(TOOL, action="send", chat_id=1, message="again", replay=True)
    ).structured_content
    assert len(w.requests) == 2  # it still went ahead
    size = f"{len(FIRST) + len(big):,}"  # the stored user text plus the oversize answer
    assert any(size in x for x in out["warnings"])
    assert any("replay" in x.lower() for x in out["warnings"])


async def test_replay_exactly_at_the_threshold_does_not_warn(chat_world):
    w = await chat_world()
    await first_turn(w)
    async with w.engine.begin() as conn:
        await conn.execute(
            text("UPDATE chat_messages SET content = :c WHERE role='assistant'"),
            {"c": "z" * (100_000 - len(FIRST))},
        )
    out = (
        await w.call(TOOL, action="send", chat_id=1, message="again", replay=True)
    ).structured_content
    assert out["warnings"] == []


async def test_replay_without_a_chat_fails_before_any_request(chat_world):
    w = await chat_world()
    result = await w.call(TOOL, action="send", message="q", title="t", replay=True)
    assert category(result) == "invalid_request" and "replay" in message(result)
    await nothing_happened(w)


async def test_only_send_is_known_so_far(chat_world):
    w = await chat_world()
    result = await w.call(TOOL, action="rename", message="q")
    assert category(result) == "invalid_request" and "action" in message(result)
    await nothing_happened(w)

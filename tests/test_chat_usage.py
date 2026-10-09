"""Task 3.7: chat recording (agent-chat "Send is recorded" and "A failed local write does not
discard a billed answer"): through ``build_server``, what ``usage_events`` holds after each send
and after the actions that make no call."""

import sqlite3

import httpx2
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
    messages_of,
    seed_chat,
    sequence,
)
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from usage_support import DbLock

from mcp_perplexity_pro.storage.engine import database_path

BAD_400 = "agent_chat_bad_previous_response_400.json"
INCOMPLETE = "agent_incomplete_truncated.json"


def then(*responders):
    def respond(request, n):
        return responders[min(n, len(responders)) - 1](request, n)

    return respond


def serve(name, status=200):
    return lambda request, n: sequence(name, status=status)(request, n)


async def test_a_first_send_and_a_follow_up_are_two_ok_events_and_the_other_actions_add_none(
    chat_world,
):
    w = await chat_world()
    await w.call(TOOL, action="send", message=FIRST, title="t", project="alpha")
    await w.call(TOOL, action="send", chat_id=1, message=FOLLOW_UP, project="alpha", depth="low")
    events = await w.events()
    assert [(e[0], e[1], e[2]) for e in events] == [(TOOL, "agent", "ok")] * 2
    assert [e[5] for e in events] == [A_ID, B_ID]  # distinct response ids
    assert [e[3] for e in events] == ["fast", "low"]  # the requested preset
    assert [e[6] for e in events] == ["alpha", "alpha"]  # the project name, also for a chain
    assert all(e[4] == "openai/gpt-6-luna" for e in events)
    before = await w.count("usage_events")
    await w.call(TOOL, action="list", project="alpha")
    await w.call(TOOL, action="read", chat_id=1, project="alpha")
    await w.call(TOOL, action="delete", chat_id=1, project="alpha", confirm=True)
    assert await w.count("usage_events") == before == 2
    assert len(w.requests) == 2


async def test_the_recorded_generic_400_on_a_chained_send_is_one_invalid_request_event(chat_world):
    w = await chat_world(then(serve(TURN_A), serve(BAD_400, 400)))
    await w.call(TOOL, action="send", message=FIRST, title="t")
    result = await w.call(TOOL, action="send", chat_id=1, message=FOLLOW_UP)
    assert category(result) == "invalid_request"
    events = await w.events()
    assert len(events) == 2
    assert (events[1][2], events[1][7], events[1][8]) == ("invalid_request", 0, "none")
    assert events[1][0] == TOOL and events[1][6] == "default"


async def test_an_incomplete_turn_is_one_unexpected_response_event_with_cost_10000(chat_world):
    w = await chat_world(sequence(INCOMPLETE))
    out = (
        await w.call(TOOL, action="send", message="essay", title="t", model="openai/gpt-6-luna")
    ).structured_content
    assert out["status"] == "incomplete"
    (event,) = await w.events()
    assert (event[0], event[2], event[7], event[8]) == (
        TOOL,
        "unexpected_response",
        10_000,
        "reported",
    )


async def test_a_failed_run_on_http_200_is_one_event_and_the_project_survives(chat_world):
    w = await chat_world(sequence(inline("failed", error={"message": "boom"})))
    result = await w.call(TOOL, action="send", message="q", title="t", project="research")
    assert category(result) == "unexpected_response"
    assert await w.rows("SELECT name FROM projects") == [("research",)]
    assert [e[2] for e in await w.events()] == ["unexpected_response"]


async def test_the_project_is_resolved_before_the_call_so_it_survives_a_failed_first_send(
    chat_world,
):
    w = await chat_world(lambda request, n: httpx2.Response(503, json={"error": {"message": "x"}}))
    result = await w.call(TOOL, action="send", message="q", title="t", project="newname")
    assert category(result) == "upstream_failure"
    assert await w.rows("SELECT name FROM projects") == [("newname",)]  # committed before the call
    assert await w.count("chats") == 0
    (event,) = await w.events()
    assert (event[2], event[6]) == ("upstream_failure", "newname")


def fail_inserts_into(w, table):
    prefix = f"INSERT INTO {table}".upper()

    @event.listens_for(w.engine.sync_engine, "before_cursor_execute")
    def boom(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(prefix):
            raise OperationalError(
                statement, parameters, sqlite3.OperationalError("database is locked")
            )


async def test_a_failed_chat_write_after_a_billed_call_keeps_the_event_and_stores_no_message(
    chat_world,
):
    w = await chat_world(sequence(TURN_A))
    fail_inserts_into(w, "chats")
    result = await w.call(TOOL, action="send", message=FIRST, title="t", project="alpha")
    out = result.structured_content
    assert not result.is_error and out["answer"] == "OK"
    assert any(x.startswith("not_saved") for x in out["warnings"])
    (event,) = await w.events()  # the event survived the rollback of the chat's own write
    assert (event[2], event[5], event[6]) == ("ok", A_ID, "alpha")
    assert await w.count("chats") == 0 and await w.count("chat_messages") == 0


async def test_a_failed_follow_up_write_leaves_the_event_and_the_stored_messages(chat_world):
    w = await chat_world(then(serve(TURN_A), serve(TURN_B)))
    await w.call(TOOL, action="send", message=FIRST, title="t")
    before = await messages_of(w, 1)
    fail_inserts_into(w, "chat_messages")
    out = (await w.call(TOOL, action="send", chat_id=1, message=FOLLOW_UP)).structured_content
    assert any(x.startswith("not_saved") for x in out["warnings"])
    assert await messages_of(w, 1) == before
    assert [e[5] for e in await w.events()] == [A_ID, B_ID]


async def test_no_write_lock_is_held_across_the_upstream_call_for_any_send(chat_world):
    w = await chat_world(then(serve(TURN_A), serve(TURN_B)))
    seen = []
    inner = w.upstream.responder

    def during(request, n):
        lock = DbLock(database_path(w.settings.data_dir))
        try:
            lock.acquire()  # raises when the tool still holds a write unit
            seen.append(n)
        finally:
            lock.close()
        return inner(request, n)

    w.upstream.responder = during
    first = await w.call(TOOL, action="send", message=FIRST, title="t")
    second = await w.call(TOOL, action="send", chat_id=1, message=FOLLOW_UP)
    assert not first.is_error and not second.is_error and seen == [1, 2]


async def test_a_seeded_chat_continues_with_its_own_project_in_the_event(chat_world):
    w = await chat_world(sequence(TURN_B))
    chat = await seed_chat(w, "alpha", "seeded")
    await w.call(TOOL, action="send", chat_id=chat, message=FOLLOW_UP, project="alpha")
    assert [e[6] for e in await w.events()] == ["alpha"]
    assert w.bodies()[0]["previous_response_id"] == "resp_2"

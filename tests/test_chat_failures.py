"""Task 3.4: the failure and incomplete cases of ``perplexity_chat`` send (agent-chat "Failed
continuation is explained", "Only complete turns are stored", "A failed local write does not
discard a billed answer")."""

import sqlite3

import httpx2
from agent_support import inline
from chat_support import (
    A_ID,
    FIRST,
    FOLLOW_UP,
    TOOL,
    TURN_A,
    TURN_B,
    category,
    message,
    messages_of,
    sequence,
)
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

BAD_400 = "agent_chat_bad_previous_response_400.json"
INCOMPLETE = "agent_incomplete_truncated.json"
TEAL = {"message": FIRST, "title": "Teal notes"}


def specific_400(request, n):
    return httpx2.Response(
        400,
        json={
            "error": {
                "message": "validation failed: input array cannot be empty",
                "type": "invalid_request",
                "code": 400,
            }
        },
    )


async def first_turn(w):
    result = await w.call(TOOL, action="send", **TEAL)
    assert not result.is_error, result.content
    return result.structured_content


def then(*responders):
    """Call 1 is served by the first responder, call 2 by the second, and so on."""

    def respond(request, n):
        return responders[min(n, len(responders)) - 1](request, n)

    return respond


def serve(name, status=200):
    return lambda request, n: sequence(name, status=status)(request, n)


# --- the generic 400 -------------------------------------------------------------------------


async def test_the_generic_400_on_a_chained_send_becomes_a_hint_that_mentions_replay(chat_world):
    w = await chat_world(then(serve(TURN_A), serve(BAD_400, 400)))
    await first_turn(w)
    before = await messages_of(w, 1)
    result = await w.call(TOOL, action="send", chat_id=1, message=FOLLOW_UP)
    assert category(result) == "invalid_request"
    assert "replay" in message(result) and "provider could not continue" in message(result)
    assert await messages_of(w, 1) == before  # nothing stored


async def test_a_validation_failed_400_passes_through_without_the_hint(chat_world):
    w = await chat_world(then(serve(TURN_A), specific_400))
    await first_turn(w)
    result = await w.call(TOOL, action="send", chat_id=1, message=FOLLOW_UP)
    assert category(result) == "invalid_request"
    assert "validation failed: input array cannot be empty" in message(result)
    assert "replay" not in message(result)


async def test_the_generic_400_on_a_first_send_or_a_replay_gets_no_hint(chat_world):
    w = await chat_world(then(serve(BAD_400, 400), serve(TURN_A), serve(BAD_400, 400)))
    first = await w.call(TOOL, action="send", **TEAL)
    assert category(first) == "invalid_request" and "replay" not in message(first)
    await w.call(TOOL, action="send", **TEAL)  # call 2 succeeds: chat 1 exists
    again = await w.call(TOOL, action="send", chat_id=1, message="q", replay=True)
    assert category(again) == "invalid_request" and "replay" not in message(again)


# --- incomplete turns ------------------------------------------------------------------------


async def test_an_incomplete_second_turn_is_returned_with_a_warning_and_not_stored(chat_world):
    w = await chat_world(then(serve(TURN_A), serve(INCOMPLETE), serve(TURN_B)))
    await first_turn(w)
    before = await messages_of(w, 1)
    result = await w.call(TOOL, action="send", chat_id=1, message="write an essay")
    out = result.structured_content
    assert not result.is_error
    assert (out["status"], out["incomplete_reason"], out["chat_id"]) == (
        "incomplete",
        "max_output_tokens",
        1,
    )
    assert out["continuation"] == "chained" and len(out["warnings"]) == 1
    assert out["chat"] is None  # nothing was stored, so no record was produced
    assert await messages_of(w, 1) == before
    await w.call(TOOL, action="send", chat_id=1, message=FOLLOW_UP)
    assert w.bodies()[2]["previous_response_id"] == A_ID  # chains from the last COMPLETE turn


async def test_an_incomplete_first_turn_creates_no_chat(chat_world):
    w = await chat_world(sequence(INCOMPLETE))
    out = (await w.call(TOOL, action="send", **TEAL)).structured_content
    assert (out["chat_id"], out["continuation"], out["status"]) == (None, "new", "incomplete")
    assert out["warnings"] and await w.count("chats") == 0 and await w.count("chat_messages") == 0
    assert await w.count("usage_events") == 1  # the call happened and was recorded


async def test_a_failed_run_on_http_200_fails_and_stores_nothing(chat_world):
    failed = inline("failed", error={"message": "boom"})
    w = await chat_world(then(serve(TURN_A), sequence(failed)))
    await first_turn(w)
    before = await messages_of(w, 1)
    result = await w.call(TOOL, action="send", chat_id=1, message="q")
    assert category(result) == "unexpected_response" and "failed" in message(result)
    assert await messages_of(w, 1) == before
    assert await w.count("usage_events") == 2  # the failed run is one event


async def test_a_run_still_in_progress_fails_and_stores_nothing(chat_world):
    w = await chat_world(sequence(inline("in_progress")))
    result = await w.call(TOOL, action="send", **TEAL)
    assert category(result) == "unexpected_response"
    assert await w.count("chats") == 0 and await w.count("usage_events") == 0


# --- the chat's own write fails after a billed call -------------------------------------------


def fail_inserts_into(w, table):
    """Make every INSERT into ``table`` fail as a busy database (what a lock held past the busy
    timeout looks like at the driver), after the usage event has been recorded."""
    statement_prefix = f"INSERT INTO {table}"

    @event.listens_for(w.engine.sync_engine, "before_cursor_execute")
    def boom(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(statement_prefix.upper()):
            raise OperationalError(
                statement, parameters, sqlite3.OperationalError("database is locked")
            )

    return boom


async def test_a_busy_database_at_the_chat_write_returns_the_answer_with_not_saved(chat_world):
    w = await chat_world(sequence(TURN_A))
    fail_inserts_into(w, "chats")
    result = await w.call(TOOL, action="send", **TEAL)
    out = result.structured_content
    assert not result.is_error and out["answer"] == "OK"
    assert any(x.startswith("not_saved") for x in out["warnings"])
    assert (out["chat_id"], out["chat"]) == (None, None) and out["continuation"] == "new"
    assert await w.count("chats") == 0 and await w.count("chat_messages") == 0
    assert await w.count("usage_events") == 1  # the event stays


async def test_a_busy_database_at_a_follow_up_write_keeps_the_event_and_the_old_anchor(chat_world):
    w = await chat_world(then(serve(TURN_A), serve(TURN_B), serve(TURN_B)))
    await first_turn(w)
    fail_inserts_into(w, "chat_messages")
    out = (await w.call(TOOL, action="send", chat_id=1, message=FOLLOW_UP)).structured_content
    assert any(x.startswith("not_saved") for x in out["warnings"])
    assert out["chat_id"] == 1 and out["answer"]
    assert await w.count("chat_messages") == 2 and await w.count("usage_events") == 2


async def test_a_chat_deleted_during_the_call_is_not_found_and_nothing_is_stored(chat_world):
    w = await chat_world(then(serve(TURN_A), serve(TURN_B)))
    await first_turn(w)
    inner = w.upstream.responder

    def delete_meanwhile(request, n):
        conn = sqlite3.connect(w.settings.data_dir / "perplexity.db")
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM chats WHERE id = 1")
            conn.commit()
        finally:
            conn.close()
        return inner(request, n)

    w.upstream.responder = delete_meanwhile
    result = await w.call(TOOL, action="send", chat_id=1, message=FOLLOW_UP)
    assert category(result) == "not_found"  # not storage_busy, not internal_error
    assert await w.count("chat_messages") == 0 and await w.count("chats") == 0
    assert await w.count("usage_events") == 2  # the call was billed and recorded

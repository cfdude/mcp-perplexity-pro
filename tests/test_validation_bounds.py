"""Gate 2 fix-ups (group B): bounded ids, a validated chat anchor, scrubbed source dates, caller
caps that match the other caps, and a log line before the research job row is inserted."""

import asyncio
import logging

import pytest
from chat_support import (
    A_ID,
    FIRST,
    FOLLOW_UP,
    TURN_A,
    TURN_B,
    category,
    message,
    messages_of,
    sequence,
    variant,
)
from research_support import RUN_ID, SUBMIT, routes

from mcp_perplexity_pro.agent import AskOptions, build_request, digest
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.models import AgentRun

KEY = "test-dummy-api-key"
BIG = 2**63


def refused(**kw):
    with pytest.raises(PerplexityError) as caught:
        build_request(AskOptions(**kw), "q", store=False)
    assert caught.value.category == "invalid_request"
    return str(caught.value)


# --- 7. the chat anchor -----------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["not a response id", "resp_" + "x" * 101, "resp_" + KEY + "!"])
async def test_an_unusable_response_id_is_not_stored_as_the_chat_anchor(chat_world, bad):
    w = await chat_world(sequence(variant(TURN_A, bad)))
    out = (
        await w.call("perplexity_chat", action="send", title="t", message=FIRST)
    ).structured_content
    assert out["chat_id"] == 1
    assert [row[2] for row in await messages_of(w, 1)] == [None, None]
    again = await w.call("perplexity_chat", action="send", chat_id=1, message=FOLLOW_UP)
    assert category(again) == "invalid_request" and "replay" in message(again)


async def test_a_turn_without_a_usable_id_is_never_skipped_for_an_older_anchor(chat_world):
    w = await chat_world(sequence(TURN_A, variant(TURN_B, "bad id"), TURN_B))
    await w.call("perplexity_chat", action="send", title="t", message=FIRST)
    await w.call("perplexity_chat", action="send", chat_id=1, message=FOLLOW_UP)  # stored, no id
    third = await w.call("perplexity_chat", action="send", chat_id=1, message="and then?")
    assert category(third) == "invalid_request"  # not chained from turn 1 (it would lose turn 2)
    assert [b.get("previous_response_id") for b in w.bodies()] == [None, A_ID]


# --- 8. source dates --------------------------------------------------------------------------


def test_a_source_date_is_scrubbed_and_capped():
    body = {
        "id": "resp_x",
        "status": "completed",
        "output": [
            {
                "type": "search_results",
                "results": [
                    {"url": "https://a.example/x", "date": f"{KEY} " + "d" * 500, "id": 1},
                ],
            }
        ],
    }
    (source,) = digest(AgentRun.model_validate(body), secrets=(KEY,)).sources
    assert KEY not in source.date and len(source.date) == 64


# --- 9. ids that do not fit the database ------------------------------------------------------


@pytest.mark.parametrize("bad", [BIG, BIG * 10, 0, -1])
@pytest.mark.parametrize("action", ["read", "delete", "send"])
async def test_an_out_of_range_chat_id_is_invalid_request_not_internal_error(
    chat_world, action, bad
):
    w = await chat_world()
    args = {"message": "hi"} if action == "send" else {"confirm": True}
    result = await w.call("perplexity_chat", action=action, chat_id=bad, **args)
    assert category(result) == "invalid_request" and "chat_id" in message(result)
    assert w.requests == []


@pytest.mark.parametrize("bad", [BIG, BIG * 10, 0, -1])
@pytest.mark.parametrize("action", ["status", "result", "cancel"])
async def test_an_out_of_range_job_id_is_invalid_request_not_internal_error(
    research_world, action, bad
):
    w = await research_world()
    result = await w.call("perplexity_jobs", action=action, job_id=bad)
    assert category(result) == "invalid_request" and "job_id" in message(result)
    assert w.requests == []


async def test_the_largest_valid_id_is_looked_up_and_not_found(research_world):
    w = await research_world()
    await w.call("perplexity_research", query="q")  # makes the project
    result = await w.call("perplexity_jobs", action="status", job_id=BIG - 1)
    assert category(result) == "not_found"


# --- 10. caller caps --------------------------------------------------------------------------


def test_a_model_over_200_characters_is_refused_and_200_is_accepted():
    assert "model" in refused(model="m" * 201)
    assert build_request(AskOptions(model="m" * 200), "q", store=False)["model"] == "m" * 200


def test_a_domain_over_253_characters_is_refused_without_echoing_it():
    text = refused(domains=["d" * 254])
    assert "domains" in text and "d" * 60 not in text
    assert build_request(AskOptions(domains=["d" * 253]), "q", store=False)


def test_a_json_schema_over_20000_serialized_characters_is_refused():
    big = {"type": "object", "properties": {"p": {"description": "x" * 20000}}}
    assert "json_schema" in refused(json_schema=big)
    small = {"type": "object", "properties": {"p": {"description": "x" * 1000}}}
    assert build_request(AskOptions(json_schema=small), "q", store=False)["response_format"]


def test_an_offending_date_or_domain_is_echoed_truncated_and_redacted():
    token = "pplx-" + "Zz9_" * 30
    for option in ("after", "before"):
        text = refused(**{option: token + "x" * 400})
        assert token[:20] not in text and len(text) < 200
    text = refused(domains=[token + " " + "y" * 400])
    assert token[:20] not in text and len(text) < 200


# --- 12. the trail before the job row is inserted ---------------------------------------------


async def test_the_response_id_is_logged_before_the_job_row_is_inserted(
    research_world, monkeypatch, caplog
):
    from mcp_perplexity_pro.tools import research

    async def hang(*args, **kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr(research, "insert_job", hang)
    w = await research_world(routes(post=[SUBMIT]))
    caplog.set_level(logging.INFO)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(w.call("perplexity_research", query="q"), 0.5)
    assert any(RUN_ID in r.getMessage() for r in caplog.records)

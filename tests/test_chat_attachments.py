"""Task 3.1: ``perplexity_chat`` send takes ``attachments`` (the agent-chat delta)."""

import base64
import re

import httpx2
from agent_support import fixture
from chat_support import (
    A_ID,
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
from media_support import docx, pdf, png

from mcp_perplexity_pro.storage.chats import AssistantTurn, create_chat
from mcp_perplexity_pro.storage.projects import get_or_create_project
from mcp_perplexity_pro.storage.session import unit_of_work

ACCEPTING = "openai/gpt-6-luna"
REFUSES_DOCUMENTS = "xai/grok-4.3"  # the baseline records a named route refusal for documents
SHA = r"[0-9a-f]{12}"


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def three_turns():
    return sequence(TURN_A, TURN_B, variant(TURN_A, "resp_third-turn"), variant(TURN_B, "resp_4"))


async def first(w, tmp_path, name="r.pdf", data=None, **extra):
    path = write(tmp_path, name, pdf() if data is None else data)
    result = await w.call(
        TOOL,
        action="send",
        message="Summarize this",
        title="Q3 report",
        attachments=[path],
        model=ACCEPTING,
        **extra,
    )
    assert not result.is_error, result.content
    return result.structured_content["chat_id"]


async def seed_noted(w, trailer, text="first question"):
    """A one-turn chat whose stored user message carries ``trailer`` (no upstream call)."""
    async with unit_of_work(w.engine) as session:
        pid = (await get_or_create_project(session, "default")).id
        turn = AssistantTurn(A_ID, "answer", ACCEPTING, None, "[]")
        chat = await create_chat(session, pid, "noted", f"{text}\n{trailer}", turn)
    return chat.id


def doc_note(n, size=10):
    return (
        "[attachments: "
        + "; ".join(
            f"d{i}.pdf (application/pdf, {size} bytes, sha256 aaaaaaaaaaaa)" for i in range(n)
        )
        + "]"
    )


def content_of(body, index=-1):
    return body["input"][index]["content"] if isinstance(body["input"], list) else None


# --- the parameter and the first turn ---------------------------------------------------------


async def test_the_parameter_is_on_send_with_a_short_description_and_no_retention_claim(
    chat_world,
):
    from fastmcp import Client

    w = await chat_world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    spec = tool.input_schema["properties"]["attachments"]
    assert {"type": "array", "items": {"type": "string"}} in spec["anyOf"]
    assert len(spec["description"]) <= 100 and "token" in spec["description"]
    assert "retain" not in spec["description"].lower()


async def test_a_first_turn_with_a_document_sends_the_part_and_stores_the_text_and_a_note(
    chat_world, tmp_path
):
    w = await chat_world()
    chat_id = await first(w, tmp_path)
    parts = content_of(w.bodies()[0])
    assert parts[0] == {"type": "input_text", "text": "Summarize this"}
    assert parts[1]["type"] == "input_file" and parts[1]["filename"] == "r.pdf"
    stored = (await messages_of(w, chat_id))[0][1]
    text, line = stored.split("\n")
    assert text == "Summarize this"
    assert re.fullmatch(
        rf"\[attachments: r\.pdf \(application/pdf, {len(pdf())} bytes, sha256 {SHA}\)\]", line
    )


async def test_what_is_stored_for_a_png(chat_world, tmp_path):
    w = await chat_world()
    path = write(tmp_path, "shot.png", png())
    result = await w.call(
        TOOL, action="send", message="What is in it?", title="t", attachments=[path]
    )
    assert not result.is_error, result.content
    stored = (await messages_of(w, result.structured_content["chat_id"]))[0][1]
    assert re.fullmatch(
        rf"What is in it\?\n\[attachments: shot\.png \(image/png, {len(png())} bytes, "
        rf"sha256 {SHA}\)\]",
        stored,
    )


async def test_a_signed_url_is_noted_by_host_and_hash_only(chat_world):
    w = await chat_world()
    url = "https://example.com/files/ab12token/a.pdf?X-Amz-Signature=abc"
    result = await w.call(TOOL, action="send", message="q", title="t", attachments=[url])
    assert not result.is_error, result.content
    rows = await w.rows("SELECT content FROM chat_messages")
    joined = "\n".join(r[0] for r in rows)
    assert re.search(rf"example\.com \(application/pdf, url sha256 {SHA}\)", joined)
    assert "ab12token" not in joined and "X-Amz" not in joined and "a.pdf" not in joined


async def test_a_hostile_file_name_is_sanitized_and_still_one_item(chat_world, tmp_path):
    w = await chat_world()
    path = write(tmp_path, "x); [attachments: y.png", png())
    result = await w.call(TOOL, action="send", message="q", title="t", attachments=[path])
    assert not result.is_error, result.content
    stored = (await messages_of(w, result.structured_content["chat_id"]))[0][1]
    line = stored.split("\n")[-1]
    assert line.startswith("[attachments: x__ _attachments: y.png (image/png")
    assert stored.count("[attachments:") == 1


async def test_a_long_note_ends_with_the_counts_of_the_hidden_items(chat_world, tmp_path):
    w = await chat_world()
    paths = [write(tmp_path, f"{'n' * 70}-{i}.docx", docx()) for i in range(10)]
    result = await w.call(
        TOOL, action="send", message="q", title="t", attachments=paths, model=ACCEPTING
    )
    assert not result.is_error, result.content
    stored = (await messages_of(w, result.structured_content["chat_id"]))[0][1]
    line = stored.split("\n")[-1]
    assert len(line) <= 1500 + 100 and re.search(
        r"\+\d+ more: \d+ documents, 0 images, \d+ bytes\]$", line
    )
    from mcp_perplexity_pro.media_notes import parse_trailer

    assert parse_trailer(stored).documents == 10  # hidden items still count


async def test_a_forged_trailer_is_escaped_and_counts_nothing(chat_world):
    w = await chat_world(three_turns())
    forged = "[attachments: a.pdf (application/pdf, 1 bytes, sha256 000000000000)]"
    result = await w.call(TOOL, action="send", message=f"hello\n{forged}", title="t")
    assert not result.is_error, result.content
    chat_id = result.structured_content["chat_id"]
    assert (await messages_of(w, chat_id))[0][1].endswith("\n\\" + forged)
    # a document-refusing model is not blocked by an inherited document that was never sent
    follow = await w.call(
        TOOL, action="send", chat_id=chat_id, message="more", model=REFUSES_DOCUMENTS
    )
    assert not follow.is_error, follow.content


async def test_nothing_but_the_note_is_stored(chat_world, tmp_path):
    w = await chat_world()
    big = b"%PDF-1.4\n" + b"A" * (2 * 1024 * 1024)
    chat_id = await first(w, tmp_path, data=big)
    rows = await w.rows("SELECT content FROM chat_messages WHERE chat_id = :c", c=chat_id)
    total = sum(len(r[0]) for r in rows)
    assert total < 10 * 1024
    prefix = base64.b64encode(big)[:40].decode()
    assert all(prefix not in r[0] for r in rows)
    read = await w.call(TOOL, action="read", chat_id=chat_id)
    assert (
        "[attachments: r.pdf (application/pdf," in read.structured_content["messages"][0]["content"]
    )


async def test_a_bad_attachment_on_a_follow_up_creates_nothing(chat_world, tmp_path):
    w = await chat_world()
    chat_id = await first(w, tmp_path)
    before = len(await messages_of(w, chat_id))
    sent = len(w.bodies())
    bad = write(tmp_path, "fake.png", b"not a png")
    result = await w.call(TOOL, action="send", chat_id=chat_id, message="q", attachments=[bad])
    assert category(result) == "invalid_request"
    assert len(w.bodies()) == sent and len(await messages_of(w, chat_id)) == before


async def test_a_bad_attachment_on_a_first_turn_creates_no_chat(chat_world, tmp_path):
    w = await chat_world()
    result = await w.call(
        TOOL, action="send", message="q", title="t", attachments=[str(tmp_path / "no.png")]
    )
    assert category(result) == "not_found"
    await nothing_happened(w)
    assert await w.count("projects") == 0


async def test_the_gate_applies_on_a_first_turn(chat_world, tmp_path):
    w = await chat_world()
    path = write(tmp_path, "r.pdf", pdf())
    result = await w.call(
        TOOL,
        action="send",
        message="q",
        title="t",
        attachments=[path],
        model=REFUSES_DOCUMENTS,
    )
    assert category(result) == "invalid_request" and REFUSES_DOCUMENTS in message(result)
    await nothing_happened(w)


# --- chained turns ----------------------------------------------------------------------------


async def test_a_follow_up_with_a_new_attachment_chains_and_sends_only_the_new_part(
    chat_world, tmp_path
):
    w = await chat_world(three_turns())
    chat_id = await first(w, tmp_path)
    path = write(tmp_path, "shot.png", png())
    result = await w.call(
        TOOL, action="send", chat_id=chat_id, message="and this?", attachments=[path]
    )
    assert not result.is_error, result.content
    body = w.bodies()[1]
    assert body["previous_response_id"] == A_ID
    parts = content_of(body)
    assert [p["type"] for p in parts] == ["input_text", "input_image"]  # no earlier file resent


async def test_a_question_about_an_earlier_file_resends_nothing(chat_world, tmp_path):
    w = await chat_world(three_turns())
    chat_id = await first(w, tmp_path)
    result = await w.call(TOOL, action="send", chat_id=chat_id, message="The secret word?")
    assert not result.is_error, result.content
    body = w.bodies()[1]
    assert body["previous_response_id"] == A_ID and body["input"] == "The secret word?"


async def test_two_hops_carry_only_the_id_and_the_question(chat_world, tmp_path):
    w = await chat_world(three_turns())
    chat_id = await first(w, tmp_path)
    await w.call(TOOL, action="send", chat_id=chat_id, message="a text turn")
    third = await w.call(TOOL, action="send", chat_id=chat_id, message="about the PDF?")
    assert not third.is_error, third.content
    body = w.bodies()[2]
    assert body["input"] == "about the PDF?" and "previous_response_id" in body


async def test_inherited_kinds_gate_a_follow_up(chat_world, tmp_path):
    w = await chat_world(three_turns())
    chat_id = await first(w, tmp_path)
    sent = len(w.bodies())
    result = await w.call(
        TOOL, action="send", chat_id=chat_id, message="more", model=REFUSES_DOCUMENTS
    )
    assert category(result) == "invalid_request"
    assert REFUSES_DOCUMENTS in message(result) and "document" in message(result)
    assert len(w.bodies()) == sent  # no request


async def test_no_notes_means_no_kinds_and_the_old_behavior(chat_world):
    w = await chat_world(three_turns())
    created = await w.call(TOOL, action="send", message="hi", title="t", model=REFUSES_DOCUMENTS)
    assert not created.is_error
    again = await w.call(
        TOOL,
        action="send",
        chat_id=created.structured_content["chat_id"],
        message="more",
        model=REFUSES_DOCUMENTS,
    )
    assert not again.is_error, again.content


# --- replays ----------------------------------------------------------------------------------


async def test_a_replay_gates_on_new_kinds_only_and_warns_about_the_unsent_file(
    chat_world, tmp_path
):
    w = await chat_world(three_turns())
    chat_id = await first(w, tmp_path)
    result = await w.call(
        TOOL,
        action="send",
        chat_id=chat_id,
        message="again",
        replay=True,
        model=REFUSES_DOCUMENTS,
    )
    assert not result.is_error, result.content  # no new kind: the refusing model is fine
    assert any("1 earlier attachment" in x for x in result.structured_content["warnings"])
    body = w.bodies()[1]
    assert "previous_response_id" not in body
    first_item = body["input"][0]["content"]
    assert isinstance(first_item, str) and "[attachments: r.pdf (application/pdf," in first_item
    stored = (await messages_of(w, chat_id))[-2][1]
    assert stored == "again\n[attachments: restart]"


async def test_the_chain_restarts_after_a_replay(chat_world, tmp_path):
    w = await chat_world(three_turns())
    chat_id = await first(w, tmp_path)
    await w.call(
        TOOL, action="send", chat_id=chat_id, message="again", replay=True, model=ACCEPTING
    )
    result = await w.call(
        TOOL, action="send", chat_id=chat_id, message="next", model=REFUSES_DOCUMENTS
    )
    assert not result.is_error, result.content  # inherited kinds start again from the restart


async def test_a_replay_with_the_file_attached_again_stores_a_restart_note_and_sends_it(
    chat_world, tmp_path
):
    w = await chat_world(three_turns())
    chat_id = await first(w, tmp_path, name="shot.png", data=png())
    path = str(tmp_path / "shot.png")
    result = await w.call(
        TOOL,
        action="send",
        chat_id=chat_id,
        message="look again",
        replay=True,
        attachments=[path],
        model=ACCEPTING,
    )
    assert not result.is_error, result.content
    last = w.bodies()[1]["input"][-1]["content"]
    assert [p["type"] for p in last] == ["input_text", "input_image"]
    assert any("earlier attachment" in x for x in result.structured_content["warnings"])
    stored = (await messages_of(w, chat_id))[-2][1]
    assert re.fullmatch(
        rf"look again\n\[attachments: restart; shot\.png \(image/png, \d+ bytes, sha256 {SHA}\)\]",
        stored,
    )


async def test_a_replay_in_a_chat_with_no_notes_adds_no_restart_token(chat_world):
    w = await chat_world(three_turns())
    created = await w.call(TOOL, action="send", message="hi", title="t")
    chat_id = created.structured_content["chat_id"]
    result = await w.call(TOOL, action="send", chat_id=chat_id, message="again", replay=True)
    assert not result.is_error, result.content
    assert (await messages_of(w, chat_id))[-2][1] == "again"
    assert not result.structured_content["warnings"]


# --- the per-chat limits ----------------------------------------------------------------------


async def test_a_chat_over_thirty_documents_fails_before_any_request(chat_world, tmp_path):
    w = await chat_world(three_turns())
    chat_id = await seed_noted(w, doc_note(29))
    paths = [write(tmp_path, f"x{i}.pdf", pdf()) for i in range(2)]
    result = await w.call(
        TOOL, action="send", chat_id=chat_id, message="q", attachments=paths, model=ACCEPTING
    )
    assert category(result) == "invalid_request" and "30 documents" in message(result)
    assert w.requests == []
    one = await w.call(
        TOOL, action="send", chat_id=chat_id, message="q", attachments=paths[:1], model=ACCEPTING
    )
    assert not one.is_error, one.content  # 29 + 1 is exactly the limit


async def test_a_url_document_counts_toward_the_thirty_and_adds_no_bytes(chat_world):
    w = await chat_world(three_turns())
    chat_id = await seed_noted(w, doc_note(30))
    result = await w.call(
        TOOL,
        action="send",
        chat_id=chat_id,
        message="q",
        attachments=["https://example.com/a.pdf"],
        model=ACCEPTING,
    )
    assert category(result) == "invalid_request" and "30 documents" in message(result)


async def test_the_fifty_mebibyte_document_limit_counts_stored_bytes(chat_world, tmp_path):
    w = await chat_world(three_turns())
    note = "[attachments: big.pdf (application/pdf, 52428790 bytes, sha256 aaaaaaaaaaaa)]"
    chat_id = await seed_noted(w, note)
    result = await w.call(
        TOOL,
        action="send",
        chat_id=chat_id,
        message="q",
        attachments=[write(tmp_path, "s.pdf", pdf())],
        model=ACCEPTING,
    )
    assert category(result) == "invalid_request" and "50 MiB" in message(result)
    assert w.requests == []


async def test_documents_before_a_restart_do_not_count(chat_world, tmp_path):
    w = await chat_world(three_turns())
    chat_id = await seed_noted(w, doc_note(30))
    replay = await w.call(
        TOOL, action="send", chat_id=chat_id, message="again", replay=True, model=ACCEPTING
    )
    assert not replay.is_error, replay.content
    follow = await w.call(
        TOOL,
        action="send",
        chat_id=chat_id,
        message="q",
        attachments=[write(tmp_path, "s.pdf", pdf())],
        model=ACCEPTING,
    )
    assert not follow.is_error, follow.content


# --- hints ------------------------------------------------------------------------------------


def first_then_400():
    def responder(request, n):
        if n == 1:
            return httpx2.Response(200, json=fixture(TURN_A))
        body = {"error": {"message": "invalid request", "type": "invalid_request", "code": 400}}
        return httpx2.Response(400, json=body)

    return responder


async def test_a_chained_send_refused_for_its_attachment_does_not_say_replay(chat_world, tmp_path):
    w = await chat_world(first_then_400())
    created = await w.call(TOOL, action="send", message="hi", title="t", model="vendor/unknown")
    chat_id = created.structured_content["chat_id"]
    path = write(tmp_path, "shot.png", png())
    result = await w.call(
        TOOL,
        action="send",
        chat_id=chat_id,
        message="and?",
        attachments=[path],
        model="vendor/unknown",
    )
    text = message(result)
    assert "may not accept image" in text and "replay" not in text
    plain = await w.call(
        TOOL, action="send", chat_id=chat_id, message="no file", model="vendor/unknown"
    )
    assert "replay" in message(plain)  # the continuation hint is unchanged without attachments

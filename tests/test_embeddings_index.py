"""Task 5.2 (py-embeddings): the ``index`` operation over a real engine and a ``MockTransport``.

The responder builds a response for any input count from REAL recorded 128-dimension vectors
(``embeddings_64_inputs_4000_chars``), with 10 tokens and 40 nano-USD per input stated by hand."""

import asyncio
import json

import httpx2
import pytest
from embeddings_support import (
    M6,
    NANO_PER_INPUT,
    REAL,
    add_chat,
    add_job,
    add_project,
    chunks,
    close_app,
    embed_response,
    events,
    make_app,
    rows,
)

from mcp_perplexity_pro import embeddings
from mcp_perplexity_pro.embeddings import index, text_hash
from mcp_perplexity_pro.errors import PerplexityError


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder=None, **settings):
        app = await make_app(
            make_settings, responder or (lambda request, n: embed_response(request)), **settings
        )
        made.append(app)
        return app

    yield build
    for app in made:
        await close_app(app)


async def run(
    app,
    *,
    source="text",
    items=None,
    project="p",
    limit=256,
    model=M6,
    dimensions=128,
    encoding="int8",
):
    return await index(
        app, project=project, source=source, items=items, model=model, dimensions=dimensions,
        encoding=encoding, limit=limit,
    )  # fmt: skip


def texts(*pairs):
    return [{"key": k, "text": t} for k, t in pairs]


async def test_chat_job_and_text_sources_store_rows_with_the_real_vector_bytes(world):
    app = await world()
    pid = await add_project(app)
    _, (m1, m2) = await add_chat(app, pid, "what is a vector", "a list of numbers")
    job = await add_job(app, pid)
    await add_job(app, pid, status="failed", result="not indexed")
    chat = await run(app, source="chat")
    jobs = await run(app, source="job")
    plain = await run(app, source="text", items=texts(("k1", "alpha text")))
    assert (chat.embedded_chunks, chat.embedded_items, chat.requests) == (2, 2, 1)
    assert (jobs.embedded_chunks, plain.embedded_chunks) == (1, 1)
    stored = await chunks(app)
    assert [(r[0], r[1], r[2], r[3]) for r in stored] == [
        ("chat", f"c:{m1}", 0, "what is a vector"),
        ("chat", f"c:{m2}", 0, "a list of numbers"),
        ("job", f"j:{job}", 0, "a research report"),
        ("text", "t:k1", 0, "alpha text"),
    ]
    assert all(r[4:7] == (M6, 128, "int8") for r in stored)
    assert stored[0][7] == REAL[0] and stored[1][7] == REAL[1]  # real bytes, in input order
    hashes = await rows(app, "SELECT text_hash FROM embedding_chunks ORDER BY id")
    assert hashes[0] == (text_hash("what is a vector"),)


async def test_a_repeat_index_sends_nothing_and_records_nothing(world):
    app = await world()
    first = await run(app, items=texts(("a", "one"), ("b", "two")))
    before = await events(app)
    again = await run(app, items=texts(("a", "one"), ("b", "two")))
    assert again.requests == 0 and again.skipped_items == 2 and again.embedded_chunks == 0
    assert app.upstream.calls == 1 and await events(app) == before and first.requests == 1


async def test_a_changed_text_replaces_only_its_own_chunks(world):
    app = await world()
    await run(app, items=texts(("a", "one"), ("b", "two")))
    first = await chunks(app)
    result = await run(app, items=texts(("a", "one changed"), ("b", "two")))
    assert (result.embedded_items, result.skipped_items) == (1, 1)
    after = await chunks(app)
    assert [(r[1], r[3]) for r in after] == [("t:b", "two"), ("t:a", "one changed")]
    assert after[0] == first[1]  # the untouched item's row is the very same row


async def test_150_chunks_with_limit_100_take_two_requests_and_a_second_call_finishes(world):
    sizes = []

    def responder(request, n):
        sizes.append(len(json.loads(request.content)["input"]))
        return embed_response(request)

    app = await world(responder)
    pid = await add_project(app)
    await add_chat(app, pid, *[f"message {i}" for i in range(150)])
    first = await run(app, source="chat", limit=100)
    assert first.requests == 2 and first.embedded_chunks == 100 and first.remaining == 50
    assert sizes == [64, 36]
    second = await run(app, source="chat", limit=100)
    assert second.embedded_chunks == 50 and second.remaining == 0 and second.skipped_items == 100
    assert sizes == [64, 36, 50] and len(await chunks(app)) == 150


async def test_limit_one_still_embeds_a_whole_item_so_a_loop_always_finishes(world):
    app = await world()
    pid = await add_project(app)
    await add_chat(app, pid, *["x" * 9000, "second"])  # the first message needs 3 chunks
    first = await run(app, source="chat", limit=1)
    assert first.embedded_chunks == 3 and first.remaining == 1
    second = await run(app, source="chat", limit=1)
    assert second.embedded_chunks == 1 and second.remaining == 0


async def test_remaining_counts_pending_chunks_left_by_the_limit(world):
    app = await world()
    items = texts(*[(f"k{i}", f"t{i}") for i in range(10)])
    result = await run(app, items=items, limit=4)
    assert result.embedded_chunks == 4 and result.remaining == 6


async def test_the_second_batch_failing_keeps_the_first_batchs_rows_and_names_the_stored_count(
    world,
):
    def responder(request, n):
        if n == 2:
            return httpx2.Response(503, json={"error": {"message": "down"}})
        return embed_response(request)

    app = await world(responder)
    items = texts(*[(f"k{i:03d}", f"t{i}") for i in range(70)])  # 64 + 6 in two batches
    with pytest.raises(PerplexityError) as caught:
        await run(app, items=items)
    assert caught.value.category == "upstream_failure"
    assert "64 chunks were stored before this failure" in str(caught.value)
    assert len(await chunks(app)) == 64
    assert [e[2] for e in await events(app)] == ["ok", "upstream_failure"]


async def test_a_wrong_length_vector_fails_after_the_event_is_recorded_and_stores_nothing(world):
    app = await world(lambda request, n: embed_response(request, wrong_length=True))
    with pytest.raises(PerplexityError) as caught:
        await run(app, items=texts(("a", "one")))
    assert caught.value.category == "unexpected_response"
    assert [e[2] for e in await events(app)] == ["ok"] and await chunks(app) == []


async def test_a_count_mismatch_is_unexpected_response_and_stores_nothing(world):
    app = await world(lambda request, n: embed_response(request, short_data=True))
    with pytest.raises(PerplexityError) as caught:
        await run(app, items=texts(("a", "one"), ("b", "two")))
    assert caught.value.category == "unexpected_response" and await chunks(app) == []


async def test_a_chat_deleted_during_the_request_is_skipped_and_the_others_are_stored(world):
    app = await world()
    pid = await add_project(app)
    doomed, _ = await add_chat(app, pid, "going away")
    _, (safe,) = await add_chat(app, pid, "staying")
    inner = app.upstream.responder

    def during(request, n):
        import sqlite3

        from mcp_perplexity_pro.storage.engine import database_path

        with sqlite3.connect(database_path(app.settings.data_dir)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM chats WHERE id = ?", (doomed,))
        return inner(request, n)

    app.upstream.responder = during
    result = await run(app, source="chat")
    assert result.embedded_chunks == 1 and result.skipped_items == 1
    assert any("deleted during the call" in w for w in result.warnings)
    assert [r[1] for r in await chunks(app)] == [f"c:{safe}"]


async def test_a_project_deleted_and_recreated_during_the_call_stores_nothing_for_old_chats(world):
    app = await world()
    pid = await add_project(app)
    await add_chat(app, pid, "old chat")
    inner = app.upstream.responder

    def during(request, n):
        import sqlite3

        from mcp_perplexity_pro.storage.engine import database_path

        with sqlite3.connect(database_path(app.settings.data_dir)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
            conn.execute("INSERT INTO projects (name) VALUES ('p')")  # recreated, new id
        return inner(request, n)

    app.upstream.responder = during
    result = await run(app, source="chat")
    assert result.embedded_chunks == 0 and result.skipped_items == 1
    assert await chunks(app) == []


async def test_two_concurrent_index_calls_embed_the_texts_once(world):
    app = await world()
    items = texts(("a", "one"), ("b", "two"))
    first, second = await asyncio.gather(run(app, items=items), run(app, items=items))
    assert app.upstream.calls == 1
    assert sorted([first.embedded_chunks, second.embedded_chunks]) == [0, 2]
    assert len(await chunks(app)) == 2 and len(await events(app)) == 1


async def test_the_stored_chunk_cap_refuses_before_any_call(world, monkeypatch):
    monkeypatch.setattr(embeddings, "MAX_STORED_CHUNKS", 3)
    app = await world()
    await run(app, items=texts(("a", "1"), ("b", "2")))
    calls = app.upstream.calls
    with pytest.raises(PerplexityError) as caught:
        await run(app, items=texts(("c", "3"), ("d", "4")))
    assert caught.value.category == "invalid_request" and "delete some" in str(caught.value)
    assert app.upstream.calls == calls and len(await chunks(app)) == 2


async def test_one_event_per_request_with_the_reported_cost_and_the_cost_sum(world):
    app = await world()
    items = texts(*[(f"k{i:03d}", f"t{i}") for i in range(70)])  # batches of 64 and 6
    result = await run(app, items=items)
    assert result.requests == 2 and result.embedded_chunks == 70
    ev = await events(app)
    assert [(e[0], e[1], e[2], e[3], e[4], e[5]) for e in ev] == [
        ("perplexity_embed", "embeddings", "ok", M6, None, "p")
    ] * 2
    assert [(e[6], e[7], e[8], e[9]) for e in ev] == [
        (640, 640, 64 * NANO_PER_INPUT, "reported"),
        (60, 60, 6 * NANO_PER_INPUT, "reported"),
    ]
    assert (result.input_tokens, result.cost_nano, result.cost_source) == (700, 2800, "reported")
    assert result.cost_usd == "0.0000028" and result.calls_cost_unknown == 0


async def test_cost_source_is_mixed_when_one_request_is_computed_and_none_when_all_unknown(world):
    def responder(request, n):
        response = embed_response(request)
        body = json.loads(response.content)
        if n == 2:
            del body["usage"]["cost"]  # no reported cost: the documented price applies
        return httpx2.Response(200, json=body)

    app = await world(responder)
    result = await run(app, items=texts(*[(f"k{i:03d}", f"t{i}") for i in range(70)]))
    assert result.cost_source == "mixed" and result.calls_cost_unknown == 0
    app2 = await world(
        lambda request, n: httpx2.Response(
            200, json={**json.loads(embed_response(request).content), "usage": None}
        )
    )
    none = await run(app2, items=texts(("a", "x")))
    assert none.cost_source == "none" and none.cost_usd is None and none.calls_cost_unknown == 1


async def test_local_refusals_send_nothing_create_nothing_and_record_nothing(world):
    app = await world()
    bad = [
        dict(items=[]), dict(items=texts(("a", "  "))), dict(items=texts(("a", "x"), ("a", "y"))),
        dict(items=texts((" ", "x"))), dict(items=texts(("a", "x" * 100_001))),
        dict(items=[{"key": f"k{i}", "text": "x"} for i in range(101)]),
        dict(source="chat", items=texts(("a", "x"))), dict(source="nope"),
        dict(items=texts(("a", "x")), limit=0), dict(items=texts(("a", "x")), limit=2049),
        dict(items=texts(("a", "x")), dimensions=130),
        dict(items=texts(("a", "x")), encoding="float"),
    ]  # fmt: skip
    for kwargs in bad:
        with pytest.raises(PerplexityError) as caught:
            await run(app, **kwargs)
        assert caught.value.category == "invalid_request", kwargs
    assert app.upstream.calls == 0 and await events(app) == []
    assert await rows(app, "SELECT count(*) FROM projects") == [(0,)]


async def test_an_unknown_project_has_nothing_to_index_for_chats_and_creates_nothing(world):
    app = await world()
    result = await run(app, source="chat", project="ghost")
    assert result.requests == 0 and result.embedded_chunks == 0
    assert await rows(app, "SELECT count(*) FROM projects") == [(0,)]


async def test_the_configured_key_is_never_sent_or_stored(world):
    app = await world()
    key = app.settings.api_key.get_secret_value()
    example = "pplx-" + "Qq7-" * 8
    body = f"use {key} and {example} with pplx-embed-v1-0.6b"
    await run(app, items=texts(("k", body)))
    sent = json.loads(app.upstream_requests[0].content)
    stored = (await chunks(app))[0][3]
    assert stored == f"use [redacted] and {example} with pplx-embed-v1-0.6b"
    assert key not in json.dumps(sent) and sent["input"] == [stored]


async def test_the_configured_key_in_an_item_key_is_redacted_in_the_ref(world):
    app = await world()
    key = app.settings.api_key.get_secret_value()
    await run(app, items=texts((f"k-{key}", "some text")))
    refs = await rows(app, "SELECT ref FROM embedding_chunks")
    assert refs == [("t:k-[redacted]",)]


async def test_lone_surrogates_are_invalid_request_never_internal_errors(world):
    app = await world()
    for items in (texts(("a", "x\ud800")), texts(("a\udfff", "x"))):
        with pytest.raises(PerplexityError) as caught:
            await run(app, items=items)
        assert caught.value.category == "invalid_request"
    assert app.upstream.calls == 0 and await events(app) == []


async def test_replacing_a_changed_item_near_the_cap_does_not_double_count_its_old_chunks(
    world, monkeypatch
):
    monkeypatch.setattr(embeddings, "MAX_STORED_CHUNKS", 2)
    app = await world()
    await run(app, items=texts(("a", "one"), ("b", "two")))  # exactly at the cap
    result = await run(app, items=texts(("a", "one changed")))  # a replace: the total stays 2
    assert result.embedded_chunks == 1 and len(await chunks(app)) == 2
    with pytest.raises(PerplexityError) as caught:  # a genuinely new item still passes the cap
        await run(app, items=texts(("c", "three")))
    assert caught.value.category == "invalid_request"


async def test_the_default_index_request_sends_the_model_and_encoding_and_no_dimensions(world):
    app = await world()
    await run(app, items=texts(("a", "one")), dimensions=None)  # the model's full size (1024)
    sent = json.loads(app.upstream_requests[0].content)
    assert sent == {"model": M6, "input": ["one"], "encoding_format": "base64_int8"}
    assert (await chunks(app))[0][5] == 1024


async def test_a_later_batch_failure_keeps_the_original_errors_status_and_api_fields(world):
    def responder(request, n):
        if n == 2:
            return httpx2.Response(
                400,
                json={"error": {"message": "bad input", "type": "invalid_request", "code": 400}},
            )
        return embed_response(request)

    app = await world(responder)
    with pytest.raises(PerplexityError) as caught:
        await run(app, items=texts(*[(f"k{i:03d}", f"t{i}") for i in range(70)]))
    assert caught.value.status == 400 and caught.value.api_type == "invalid_request"
    assert caught.value.api_message == "bad input"

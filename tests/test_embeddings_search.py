"""Task 6.2 (py-embeddings): the ``search`` operation with hand-built stored vectors."""

import asyncio
import json

import numpy as np
import pytest
from embeddings_support import (
    M4,
    M6,
    add_chat,
    add_job,
    add_project,
    close_app,
    events,
    fixed_response,
    make_app,
    rows,
)

from mcp_perplexity_pro.embeddings import search
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.embeddings import ChunkRow, insert_chunks
from mcp_perplexity_pro.storage.session import unit_of_work

DIMS = 128
SECOND = np.full(DIMS, 10, dtype=np.int8)  # the query equals this one
FIRST = np.concatenate([np.full(96, 10), np.zeros(32)]).astype(np.int8)  # cosine sqrt(0.75)
THIRD = np.full(DIMS, -10, dtype=np.int8)  # opposite


def chunk_row(source, ref, vector, *, text="text", model=M6, encoding="int8", **keys):
    return ChunkRow(source, ref, 0, text, "h", model, DIMS, encoding, vector, **keys)


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(query_vector=None):
        query_vector = SECOND.tobytes() if query_vector is None else query_vector
        app = await make_app(
            make_settings, lambda request, n: fixed_response(request, query_vector)
        )
        made.append(app)
        return app

    yield build
    for app in made:
        await close_app(app)


async def store_rows(app, pid, rows_):
    async with unit_of_work(app.engine) as session:
        return await insert_chunks(session, pid, rows_)


async def go(app, query="what", **kwargs):
    arguments = dict(
        project="p", query=query, top_k_value=5, min_score=None, source=None, model=M6,
        dimensions=DIMS, encoding="int8",
    )  # fmt: skip
    arguments.update(kwargs)
    return await search(app, **arguments)


async def seed(app):
    pid = await add_project(app)
    await store_rows(
        app,
        pid,
        [
            chunk_row("text", "t:first", FIRST.tobytes(), text="first text"),
            chunk_row("text", "t:second", SECOND.tobytes(), text="second text"),
            chunk_row("text", "t:third", THIRD.tobytes(), text="third text"),
        ],
    )
    return pid


async def test_ranking_is_second_first_third_with_the_expected_scores(world):
    app = await world()
    await seed(app)
    result = await go(app)
    assert [h.key for h in result.hits] == ["second", "first", "third"]
    assert [round(h.score, 4) for h in result.hits] == [1.0, 0.866, -1.0]
    assert result.requests == 1 and result.candidates == 3
    assert [e[:3] for e in await events(app)] == [("perplexity_embed", "embeddings", "ok")]


async def test_top_k_min_score_and_source_filters(world):
    app = await world()
    pid = await seed(app)
    job = await add_job(app, pid)
    await store_rows(
        app, pid, [chunk_row("job", f"j:{job}", SECOND.tobytes(), research_job_id=job)]
    )
    assert len((await go(app, top_k_value=1)).hits) == 1
    assert [h.key for h in (await go(app, min_score=0.5)).hits if h.key] == ["second", "first"]
    only_job = await go(app, source="job")
    assert [(h.source, h.job_id) for h in only_job.hits] == [("job", job)]


async def test_hit_fields_cover_chat_job_and_text_references(world):
    app = await world()
    pid = await add_project(app)
    chat, (message,) = await add_chat(app, pid, "chat words")
    job = await add_job(app, pid)
    await store_rows(
        app,
        pid,
        [
            chunk_row(
                "chat", f"c:{message}", SECOND.tobytes(), text="c" * 900, chat_message_id=message
            ),
            chunk_row("job", f"j:{job}", FIRST.tobytes(), research_job_id=job),
            chunk_row("text", "t:key", THIRD.tobytes()),
        ],
    )
    hits = (await go(app)).hits
    assert (hits[0].source, hits[0].chat_id, hits[0].message_id) == ("chat", chat, message)
    assert len(hits[0].text) == 800 and hits[0].chunk_index == 0
    assert (hits[1].source, hits[1].job_id) == ("job", job)
    assert (hits[2].source, hits[2].key) == ("text", "key")


async def test_binary_search_ranks_by_hamming_similarity(world):
    packed = lambda bits: bytes(bits)  # noqa: E731
    query = packed([0xFF] * 16)
    app = await world(query_vector=query)
    pid = await add_project(app)
    await store_rows(
        app,
        pid,
        [
            chunk_row("text", "t:same", query, encoding="binary"),
            chunk_row("text", "t:half", packed([0xFF] * 8 + [0x00] * 8), encoding="binary"),
            chunk_row("text", "t:none", packed([0x00] * 16), encoding="binary"),
        ],
    )
    result = await go(app, encoding="binary")
    assert [(h.key, round(h.score, 3)) for h in result.hits] == [
        ("same", 1.0), ("half", 0.5), ("none", 0.0),
    ]  # fmt: skip


async def test_only_chunks_of_the_same_triple_are_compared(world):
    app = await world()
    pid = await add_project(app)
    await store_rows(
        app,
        pid,
        [
            chunk_row("text", "t:a", SECOND.tobytes()),
            chunk_row("text", "t:b", SECOND.tobytes(), model=M4),
            chunk_row("text", "t:c", np.ones(16, dtype=np.int8).tobytes() * 8, encoding="binary"),
        ],
    )
    result = await go(app)
    assert [h.key for h in result.hits] == ["a"] and result.candidates == 1


async def test_nothing_to_compare_sends_no_request_and_records_no_event(world):
    app = await world()
    await add_project(app)
    empty = await go(app)
    ghost = await go(app, project="ghost")
    for result in (empty, ghost):
        assert result.hits == [] and result.requests == 0 and result.warnings
    assert app.upstream.calls == 0 and await events(app) == []
    assert await rows(app, "SELECT count(*) FROM projects") == [(1,)]  # ghost was not created


async def test_the_key_is_scrubbed_from_hit_text_while_examples_and_model_ids_are_kept(world):
    app = await world()
    pid = await add_project(app)
    key = app.settings.api_key.get_secret_value()
    example = "pplx-" + "Qq7-" * 8
    body = f"key {key} model pplx-embed-v1-0.6b example {example}"
    await store_rows(app, pid, [chunk_row("text", "t:k", SECOND.tobytes(), text=body)])
    (hit,) = (await go(app)).hits
    assert hit.text == f"key [redacted] model pplx-embed-v1-0.6b example {example}"


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(query=""), dict(query="   "), dict(query="x" * 4001), dict(top_k_value=0),
        dict(top_k_value=21), dict(top_k_value=True), dict(min_score=1.5), dict(min_score=-1.5),
        dict(min_score="0.5"), dict(source="chats"), dict(dimensions=130), dict(encoding="float"),
    ],
)  # fmt: skip
async def test_refusals_happen_before_any_call(world, kwargs):
    app = await world()
    await seed(app)
    with pytest.raises(PerplexityError) as caught:
        await go(app, **kwargs)
    assert caught.value.category == "invalid_request" and app.upstream.calls == 0


async def test_a_query_vector_that_fails_decoding_is_unexpected_response_with_the_event(world):
    app = await world(query_vector=b"\x01" * 5)  # not 128 bytes
    await seed(app)
    with pytest.raises(PerplexityError) as caught:
        await go(app)
    assert caught.value.category == "unexpected_response"
    assert [e[2] for e in await events(app)] == ["ok"]


async def test_the_event_loop_stays_responsive_during_a_20000_row_search(world):
    app = await world(query_vector=SECOND.tobytes())
    pid = await add_project(app)
    rng = np.random.default_rng(1)
    data = rng.integers(-100, 100, size=(20_000, DIMS), dtype=np.int8)
    batch = [chunk_row("text", f"t:{i}", data[i].tobytes()) for i in range(20_000)]
    for start in range(0, 20_000, 2000):
        await store_rows(app, pid, batch[start : start + 2000])
    ticks = []

    async def ticker():
        while True:
            ticks.append(1)
            await asyncio.sleep(0.001)

    task = asyncio.create_task(ticker())
    try:
        result = await go(app, top_k_value=5)
    finally:
        task.cancel()
    assert result.candidates == 20_000 and len(result.hits) == 5 and len(ticks) > 3
    assert json.dumps([h.score for h in result.hits])  # scores are plain floats

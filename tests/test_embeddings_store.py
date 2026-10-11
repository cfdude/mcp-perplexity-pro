"""Task 3.3 (py-embeddings): the storage operations over a real database."""

from datetime import datetime

import pytest
from sqlalchemy import select, text

from mcp_perplexity_pro.storage import embeddings as store
from mcp_perplexity_pro.storage.embeddings import ChunkRow
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate
from mcp_perplexity_pro.storage.models import Chat, ChatMessage, Project, ResearchJob
from mcp_perplexity_pro.storage.session import unit_of_work

NOW = datetime(2026, 10, 11, 12, 0, 0)
TRIPLE = ("m1", 8, "int8")


@pytest.fixture
async def engine(make_settings):
    settings = make_settings()
    migrate(settings)
    engine = create_engine_for(settings)
    yield engine
    await engine.dispose()


async def project(engine, name="p"):
    async with unit_of_work(engine) as session:
        proj = Project(name=name)
        session.add(proj)
        await session.flush()
        return proj.id


async def add_chat(engine, pid, *contents):
    async with unit_of_work(engine) as session:
        chat = Chat(project_id=pid, title="t", created_at=NOW, updated_at=NOW)
        session.add(chat)
        await session.flush()
        ids = []
        for i, content in enumerate(contents):
            message = ChatMessage(
                chat_id=chat.id,
                role="user" if i % 2 == 0 else "assistant",
                content=content,
                created_at=NOW,
            )
            session.add(message)
            await session.flush()
            ids.append(message.id)
        return chat.id, ids


_serial = iter(range(1, 10_000))


async def add_job(engine, pid, status="completed", result="a report"):
    async with unit_of_work(engine) as session:
        job = ResearchJob(
            project_id=pid,
            query="q",
            depth="medium",
            response_id=f"resp_{next(_serial)}",
            status=status,
            started_at=NOW,
            result_text=result,
        )
        session.add(job)
        await session.flush()
        return job.id


def row(source, ref, *, index=0, digest="h", vector=b"\x01" * 8, model="m1", **keys):
    return ChunkRow(source, ref, index, f"text {ref}", digest, model, 8, "int8", vector, **keys)


async def test_source_items_for_chats_cover_both_roles_in_order_and_for_jobs_only_completed(engine):
    pid = await project(engine)
    _, (m1, m2) = await add_chat(engine, pid, "question", "answer")
    done = await add_job(engine, pid)
    await add_job(engine, pid, status="failed", result="partial")
    await add_job(engine, pid, status="incomplete", result="cut")
    await add_job(engine, pid, status="completed", result=None)
    async with unit_of_work(engine, write=False) as session:
        chats = await store.source_items(session, pid, "chat")
        jobs = await store.source_items(session, pid, "job")
    assert [(i.ref, i.text) for i in chats] == [(f"c:{m1}", "question"), (f"c:{m2}", "answer")]
    assert [i.ref for i in jobs] == [f"j:{done}"] and jobs[0].research_job_id == done


async def test_a_text_key_replaced_for_one_triple_leaves_the_other_triple_alone(engine):
    pid = await project(engine)
    async with unit_of_work(engine) as session:
        await store.insert_chunks(session, pid, [row("text", "t:k", digest="old")], now=NOW)
        await store.insert_chunks(
            session, pid, [row("text", "t:k", digest="o2", model="m2")], now=NOW
        )
    async with unit_of_work(engine) as session:
        assert await store.delete_item_chunks(session, pid, "t:k", *TRIPLE) == 1
        await store.insert_chunks(session, pid, [row("text", "t:k", digest="new")], now=NOW)
    async with unit_of_work(engine, write=False) as session:
        assert await store.stored_hashes(session, pid, *TRIPLE) == {"t:k": {0: "new"}}
        assert await store.stored_hashes(session, pid, "m2", 8, "int8") == {"t:k": {0: "o2"}}
        assert await store.stored_hashes(session, pid, *TRIPLE, source="chat") == {}


async def test_insert_skips_vanished_sources_and_ignores_existing_chunks(engine):
    pid, other = await project(engine), await project(engine, "other")
    chat, (message,) = await add_chat(engine, pid, "hello")
    job = await add_job(engine, pid)
    rows = [
        row("chat", f"c:{message}", chat_message_id=message),
        row("chat", "c:999", chat_message_id=999),  # no such message
        row("job", f"j:{job}", research_job_id=job),
        row("job", "j:999", research_job_id=999),
        row("text", "t:k"),
    ]
    async with unit_of_work(engine) as session:
        inserted, gone = await store.insert_chunks(session, pid, rows, now=NOW)
    assert len(inserted) == 3 and gone == ["c:999", "j:999"]
    async with unit_of_work(engine) as session:
        again, gone_again = await store.insert_chunks(session, pid, rows[:1], now=NOW)
    assert again == [] and gone_again == []  # an existing chunk is neither inserted nor gone
    # a message of ANOTHER project is gone for this project
    async with unit_of_work(engine) as session:
        _, gone_other = await store.insert_chunks(
            session, other, [row("chat", f"c:{message}", chat_message_id=message)], now=NOW
        )
    assert gone_other == [f"c:{message}"]


async def test_insert_into_a_deleted_project_reports_every_sourced_chunk_gone(engine):
    pid = await project(engine)
    _, (message,) = await add_chat(engine, pid, "x")
    async with unit_of_work(engine) as session:
        await session.execute(text("DELETE FROM projects WHERE id = :p"), {"p": pid})
    async with unit_of_work(engine) as session:
        _, gone = await store.insert_chunks(
            session, pid, [row("chat", f"c:{message}", chat_message_id=message)], now=NOW
        )
    assert gone == [f"c:{message}"]


async def test_counts_groups_and_triple_totals(engine):
    pid = await project(engine)
    async with unit_of_work(engine) as session:
        await store.insert_chunks(
            session,
            pid,
            [row("text", "t:a"), row("text", "t:b"), row("text", "t:a", model="m2", index=1)],
            now=NOW,
        )
    async with unit_of_work(engine, write=False) as session:
        assert await store.count_for_triple(session, pid, *TRIPLE) == 2
        assert await store.count_by_group(session, pid) == [
            ("text", "m1", 8, "int8", 2),
            ("text", "m2", 8, "int8", 1),
        ]


async def test_delete_filters_by_source_and_by_model_and_an_omitted_filter_matches_all(engine):
    pid = await project(engine)
    _, (message,) = await add_chat(engine, pid, "x")
    async with unit_of_work(engine) as session:
        await store.insert_chunks(
            session,
            pid,
            [
                row("chat", f"c:{message}", chat_message_id=message),
                row("text", "t:a"),
                row("text", "t:b", model="m2"),
            ],
            now=NOW,
        )
    async with unit_of_work(engine) as session:
        assert await store.delete_chunks(session, pid, source="chat") == 1
        assert await store.delete_chunks(session, pid, model="m2") == 1
        assert await store.delete_chunks(session, pid) == 1  # everything left
        assert await store.delete_chunks(session, pid) == 0


async def test_candidates_select_ids_and_vectors_only_and_hits_carry_text_and_chat_id(engine):
    pid = await project(engine)
    chat, (message,) = await add_chat(engine, pid, "hi")
    async with unit_of_work(engine) as session:
        inserted, _ = await store.insert_chunks(
            session,
            pid,
            [
                row("chat", f"c:{message}", chat_message_id=message, vector=b"\x07" * 8),
                row("text", "t:a", vector=b"\x09" * 8),
            ],
            now=NOW,
        )
    async with unit_of_work(engine, write=False) as session:
        candidates = await store.candidate_vectors(session, pid, *TRIPLE)
        assert candidates == [(inserted[0], b"\x07" * 8), (inserted[1], b"\x09" * 8)]
        assert [
            c for c, _ in await store.candidate_vectors(session, pid, *TRIPLE, source="text")
        ] == [inserted[1]]
        hits = await store.hit_details(session, [inserted[0], inserted[1]])
        assert await store.hit_details(session, []) == {}
    assert hits[inserted[0]].chat_id == chat and hits[inserted[0]].text == f"text c:{message}"
    assert hits[inserted[1]].chat_id is None and hits[inserted[1]].ref == "t:a"


def test_the_candidate_query_names_no_text_column():
    import inspect

    source = inspect.getsource(store.candidate_vectors)
    assert "EmbeddingChunk.text" not in source and "select(EmbeddingChunk)" not in source


async def test_the_module_imports_nothing_from_embeddings_py():
    import inspect

    assert "mcp_perplexity_pro.embeddings" not in inspect.getsource(store)
    assert select  # keep the sqlalchemy import used for the readability of the module test

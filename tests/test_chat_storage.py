"""Task 3.2: the chat storage operations (agent-chat "Chat storage", design D6 and D15), with a
real engine on a migrated temporary database."""

import pytest
from sqlalchemy import text

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.chats import (
    AssistantTurn,
    append_turn,
    chat_history,
    create_chat,
    delete_chat,
    last_anchor,
    list_chats,
    load_chat,
    read_messages,
)
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate
from mcp_perplexity_pro.storage.projects import find_project, get_or_create_project
from mcp_perplexity_pro.storage.session import unit_of_work


@pytest.fixture
async def engine(make_settings):
    settings = make_settings()
    migrate(settings)
    engine = create_engine_for(settings)
    yield engine
    await engine.dispose()


def turn(n: int, text_: str | None = None) -> AssistantTurn:
    return AssistantTurn(
        response_id=f"resp_{n}",
        content=text_ if text_ is not None else f"answer {n}",
        model="openai/gpt-6-luna",
        preset="fast",
        sources_json='[{"url": "https://a.example"}]',
    )


async def project_id(engine, name="alpha") -> int:
    async with unit_of_work(engine) as session:
        return (await get_or_create_project(session, name)).id


async def rows(engine, sql, **params):
    async with engine.connect() as conn:
        return [tuple(r) for r in await conn.execute(text(sql), params)]


async def start(engine, pid, title="t", n=1):
    async with unit_of_work(engine) as session:
        return (await create_chat(session, pid, title, f"question {n}", turn(n))).id


async def test_a_first_turn_stores_one_chat_and_two_messages_and_sets_the_anchor(engine):
    pid = await project_id(engine)
    async with unit_of_work(engine) as session:
        chat = await create_chat(session, pid, "Teal notes", "question 1", turn(1))
    assert (chat.title, chat.message_count) == ("Teal notes", 2)
    assert await rows(engine, "SELECT count(*) FROM chats") == [(1,)]
    assert await rows(
        engine, "SELECT role, content, response_id, model, preset FROM chat_messages ORDER BY id"
    ) == [
        ("user", "question 1", None, None, None),
        ("assistant", "answer 1", "resp_1", "openai/gpt-6-luna", "fast"),
    ]
    async with unit_of_work(engine, write=False) as session:
        assert await last_anchor(session, chat.id) == "resp_1"


async def test_an_append_moves_the_anchor_and_the_update_time(engine):
    pid = await project_id(engine)
    cid = await start(engine, pid)
    before = (await rows(engine, "SELECT updated_at FROM chats"))[0][0]
    async with unit_of_work(engine) as session:
        chat = await append_turn(session, pid, cid, "question 2", turn(2))
    assert chat.message_count == 4
    async with unit_of_work(engine, write=False) as session:
        assert await last_anchor(session, cid) == "resp_2"
    assert (await rows(engine, "SELECT updated_at FROM chats"))[0][0] > before


async def test_the_replay_history_is_every_message_in_order(engine):
    pid = await project_id(engine)
    cid = await start(engine, pid)
    async with unit_of_work(engine) as session:
        await append_turn(session, pid, cid, "question 2", turn(2))
    async with unit_of_work(engine, write=False) as session:
        assert await chat_history(session, cid) == [
            ("user", "question 1"),
            ("assistant", "answer 1"),
            ("user", "question 2"),
            ("assistant", "answer 2"),
        ]


async def test_a_chat_of_another_project_is_not_found(engine):
    a, b = await project_id(engine, "a"), await project_id(engine, "b")
    cid = await start(engine, a)
    async with unit_of_work(engine, write=False) as session:
        assert (await load_chat(session, a, cid)).id == cid
        for other_project, chat in ((b, cid), (a, cid + 99)):
            with pytest.raises(PerplexityError) as err:
                await load_chat(session, other_project, chat)
            assert err.value.category == "not_found"
    async with unit_of_work(engine) as session:
        with pytest.raises(PerplexityError) as err:
            await append_turn(session, b, cid, "q", turn(9))
        assert err.value.category == "not_found"
    assert await rows(engine, "SELECT count(*) FROM chat_messages") == [(2,)]


async def test_find_project_of_an_absent_name_returns_none_and_creates_nothing(engine):
    await project_id(engine, "real")
    async with unit_of_work(engine, write=False) as session:
        assert await find_project(session, "ghost") is None
        assert (await find_project(session, "real")).name == "real"
        assert (await find_project(session, None)) is None  # default is absent too
    assert await rows(engine, "SELECT name FROM projects") == [("real",)]
    with pytest.raises(PerplexityError) as err:
        async with unit_of_work(engine, write=False) as session:
            await find_project(session, "bad name!")
    assert err.value.category == "invalid_request"


async def test_list_is_newest_updated_first_and_limit_reports_total_and_truncation(engine):
    pid = await project_id(engine)
    first = await start(engine, pid, "first", 1)
    second = await start(engine, pid, "second", 2)
    third = await start(engine, pid, "third", 3)
    other = await project_id(engine, "elsewhere")
    await start(engine, other, "not mine", 4)
    async with unit_of_work(engine) as session:
        await append_turn(session, pid, first, "again", turn(5))  # the oldest is now newest
    async with unit_of_work(engine, write=False) as session:
        chats, total = await list_chats(session, pid, 20)
        assert [c.id for c in chats] == [first, third, second]
        assert (total, [c.message_count for c in chats]) == (3, [4, 2, 2])
        cut, total = await list_chats(session, pid, 2)
        assert ([c.id for c in cut], total) == ([first, third], 3)


async def test_read_returns_the_last_n_in_chronological_order_with_the_total(engine):
    pid = await project_id(engine)
    cid = await start(engine, pid)
    async with unit_of_work(engine) as session:
        await append_turn(session, pid, cid, "question 2", turn(2))
    async with unit_of_work(engine, write=False) as session:
        everything, total = await read_messages(session, cid, 50)
        assert (total, [m.content for m in everything]) == (
            4,
            ["question 1", "answer 1", "question 2", "answer 2"],
        )
        last, total = await read_messages(session, cid, 3)
        assert (total, [m.content for m in last]) == (4, ["answer 1", "question 2", "answer 2"])
        assert last[-1].response_id == "resp_2" and last[0].role == "assistant"


async def test_delete_reports_the_removed_message_count_and_cascades(engine):
    pid = await project_id(engine)
    cid = await start(engine, pid)
    keep = await start(engine, pid, "keep", 2)
    async with unit_of_work(engine) as session:
        await append_turn(session, pid, cid, "q", turn(3))
    async with unit_of_work(engine) as session:
        assert await delete_chat(session, pid, cid) == 4
    assert await rows(engine, "SELECT id FROM chats") == [(keep,)]
    assert await rows(engine, "SELECT count(*) FROM chat_messages") == [(2,)]
    async with unit_of_work(engine) as session:
        with pytest.raises(PerplexityError) as err:
            await delete_chat(session, pid, cid)
        assert err.value.category == "not_found"


async def test_a_failure_inside_the_unit_leaves_nothing_stored(engine):
    pid = await project_id(engine)
    cid = await start(engine, pid)
    with pytest.raises(RuntimeError):
        async with unit_of_work(engine) as session:
            await create_chat(session, pid, "never", "q", turn(7))
            await append_turn(session, pid, cid, "q", turn(8))
            raise RuntimeError("the tool failed after its writes")
    assert await rows(engine, "SELECT title FROM chats") == [("t",)]
    assert await rows(engine, "SELECT count(*) FROM chat_messages") == [(2,)]


async def test_an_append_to_a_chat_deleted_in_between_is_not_found(engine):
    pid = await project_id(engine)
    cid = await start(engine, pid)
    async with unit_of_work(engine) as session:
        await delete_chat(session, pid, cid)
    with pytest.raises(PerplexityError) as err:
        async with unit_of_work(engine) as session:
            await append_turn(session, pid, cid, "late", turn(2))
    # not storage_busy and not internal_error: retrying cannot help
    assert err.value.category == "not_found"
    assert await rows(engine, "SELECT count(*) FROM chat_messages") == [(0,)]


async def test_a_first_turn_for_a_project_deleted_in_between_is_not_found(engine):
    pid = await project_id(engine)
    async with unit_of_work(engine) as session:
        await session.execute(text("DELETE FROM projects WHERE id = :i"), {"i": pid})
    with pytest.raises(PerplexityError) as err:
        async with unit_of_work(engine) as session:
            await create_chat(session, pid, "orphan", "q", turn(1))
    assert err.value.category == "not_found"  # an IntegrityError, mapped
    assert await rows(engine, "SELECT count(*) FROM chats") == [(0,)]

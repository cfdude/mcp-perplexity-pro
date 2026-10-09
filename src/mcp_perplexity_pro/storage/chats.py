"""Chat storage operations (agent-chat spec; design D6).

Every function runs inside the caller's unit of work and never opens one, so a tool composes
them into one atomic write (or one read). A write that fails because the chat or its project is
gone (a missing row, or an ``IntegrityError`` from the foreign keys) raises ``PerplexityError``
``not_found``: retrying cannot help, so it must not surface as ``storage_busy`` or
``internal_error``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.storage.models import Chat, ChatMessage
from mcp_perplexity_pro.usage import utcnow


@dataclass(frozen=True)
class AssistantTurn:
    """What an assistant message keeps: the text and what the API returned for it."""

    response_id: str | None
    content: str
    model: str | None = None
    preset: str | None = None
    sources_json: str | None = None


@dataclass(frozen=True)
class ChatSummary:
    id: int
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredMessage:
    id: int
    role: str
    content: str
    created_at: datetime
    response_id: str | None
    model: str | None
    preset: str | None
    sources_json: str | None


def _gone(what: str, chat_id: int | None = None) -> PerplexityError:
    named = f"Chat {chat_id}" if chat_id is not None else what
    return PerplexityError(
        "not_found", f"{named} does not exist in this project (it may have been removed)."
    )


def _messages(chat_id: int, user_text: str, turn: AssistantTurn, now: datetime):
    return [
        ChatMessage(chat_id=chat_id, role="user", content=user_text, created_at=now),
        ChatMessage(
            chat_id=chat_id,
            role="assistant",
            content=turn.content,
            created_at=now,
            response_id=turn.response_id,
            model=turn.model,
            preset=turn.preset,
            sources_json=turn.sources_json,
        ),
    ]


async def _count(session: AsyncSession, chat_id: int) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.chat_id == chat_id)
        )
    ).scalar_one()


async def _summary(session: AsyncSession, chat: Chat) -> ChatSummary:
    return ChatSummary(
        id=chat.id,
        title=chat.title,
        message_count=await _count(session, chat.id),
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


async def create_chat(
    session: AsyncSession, project_id: int, title: str, user_text: str, turn: AssistantTurn
) -> ChatSummary:
    """A new chat with its first two messages, in the caller's one unit of work."""
    now = utcnow()
    chat = Chat(project_id=project_id, title=title, created_at=now, updated_at=now)
    try:
        session.add(chat)
        await session.flush()
        session.add_all(_messages(chat.id, user_text, turn, now))
        await session.flush()
    except IntegrityError:
        raise _gone("The project") from None
    return await _summary(session, chat)


async def append_turn(
    session: AsyncSession, project_id: int, chat_id: int, user_text: str, turn: AssistantTurn
) -> ChatSummary:
    """Append a completed turn (user message, assistant message) and move the chat's update
    time. The anchor for the next send is then this turn's response id."""
    chat = await load_chat(session, project_id, chat_id)
    now = utcnow()
    try:
        session.add_all(_messages(chat.id, user_text, turn, now))
        chat.updated_at = now
        await session.flush()
    except IntegrityError:
        raise _gone("The chat", chat_id) from None
    return await _summary(session, chat)


async def load_chat(session: AsyncSession, project_id: int, chat_id: int) -> Chat:
    """The chat, scoped to its project: another project's chat, or none, is ``not_found``."""
    chat = (
        await session.execute(select(Chat).where(Chat.id == chat_id, Chat.project_id == project_id))
    ).scalar_one_or_none()
    if chat is None:
        raise _gone("The chat", chat_id)
    return chat


async def chat_summary(session: AsyncSession, chat: Chat) -> ChatSummary:
    return await _summary(session, chat)


async def last_anchor(session: AsyncSession, chat_id: int) -> str | None:
    """The response id of the chat's last assistant message: the next send's
    ``previous_response_id``. ``None`` when the chat has no assistant message, or when the last
    one has no usable id (never an older turn's id: chaining from it would drop the last turn)."""
    return (
        await session.execute(
            select(ChatMessage.response_id)
            .where(
                ChatMessage.chat_id == chat_id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def chat_history(session: AsyncSession, chat_id: int) -> list[tuple[str, str]]:
    """Every message as ``(role, content)``, oldest first: the input of a replay."""
    rows = await session.execute(
        select(ChatMessage.role, ChatMessage.content)
        .where(ChatMessage.chat_id == chat_id)
        .order_by(ChatMessage.id)
    )
    return [(role, content) for role, content in rows]


async def list_chats(
    session: AsyncSession, project_id: int, limit: int
) -> tuple[list[ChatSummary], int]:
    """The project's chats, newest-updated first, at most ``limit``, and the total."""
    counts = (
        select(ChatMessage.chat_id, func.count().label("n"))
        .group_by(ChatMessage.chat_id)
        .subquery()
    )
    rows = await session.execute(
        select(Chat, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.chat_id == Chat.id)
        .where(Chat.project_id == project_id)
        .order_by(Chat.updated_at.desc(), Chat.id.desc())
        .limit(limit)
    )
    chats = [ChatSummary(c.id, c.title, n, c.created_at, c.updated_at) for c, n in rows]
    total = (
        await session.execute(
            select(func.count()).select_from(Chat).where(Chat.project_id == project_id)
        )
    ).scalar_one()
    return chats, total


async def read_messages(
    session: AsyncSession, chat_id: int, limit: int
) -> tuple[list[StoredMessage], int]:
    """The last ``limit`` messages in chronological order, and the chat's message total."""
    rows = (
        (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.chat_id == chat_id)
                .order_by(ChatMessage.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    messages = [
        StoredMessage(
            m.id, m.role, m.content, m.created_at, m.response_id, m.model, m.preset, m.sources_json
        )
        for m in reversed(rows)
    ]
    return messages, await _count(session, chat_id)


async def delete_chat(session: AsyncSession, project_id: int, chat_id: int) -> int:
    """Remove the chat; its messages go by cascade. Returns how many messages were removed."""
    await load_chat(session, project_id, chat_id)
    removed = await _count(session, chat_id)
    await session.execute(delete(Chat).where(Chat.id == chat_id, Chat.project_id == project_id))
    return removed

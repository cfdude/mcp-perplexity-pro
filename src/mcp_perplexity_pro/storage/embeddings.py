"""Embedding chunk storage operations (embeddings-store spec; design D4 to D7, D9).

Every function runs inside the caller's unit of work and never opens one. This module imports
nothing from ``embeddings.py``: it takes hashes, chunks and vectors as arguments, so the
orchestration module can use it without a cycle. ``vector`` bytes are returned only by
``candidate_vectors`` (to the scorer); no other function reads them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_perplexity_pro.storage.models import (
    Chat,
    ChatMessage,
    EmbeddingChunk,
    ResearchJob,
)
from mcp_perplexity_pro.usage import utcnow


@dataclass(frozen=True)
class SourceItem:
    """One thing that can be indexed: a chat message or a completed job's result."""

    source: str  # chat | job
    ref: str  # c:<id> | j:<id>
    text: str
    chat_message_id: int | None = None
    research_job_id: int | None = None


@dataclass(frozen=True)
class ChunkRow:
    """One chunk ready to store."""

    source: str
    ref: str
    chunk_index: int
    text: str
    text_hash: str
    model: str
    dimensions: int
    encoding: str
    vector: bytes
    chat_message_id: int | None = None
    research_job_id: int | None = None


@dataclass(frozen=True)
class Hit:
    """The details of a winning chunk (never its vector)."""

    id: int
    source: str
    ref: str
    chunk_index: int
    text: str
    chat_message_id: int | None
    research_job_id: int | None
    chat_id: int | None


async def source_items(session: AsyncSession, project_id: int, source: str) -> list[SourceItem]:
    """The project's indexable items for ``source`` (``chat`` or ``job``), oldest first. Text
    blankness is the caller's rule (one helper decides it for ``index`` and ``status``)."""
    if source == "chat":
        rows = await session.execute(
            select(ChatMessage.id, ChatMessage.content)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(Chat.project_id == project_id)
            .order_by(ChatMessage.id)
        )
        return [SourceItem("chat", f"c:{i}", content, chat_message_id=i) for i, content in rows]
    rows = await session.execute(
        select(ResearchJob.id, ResearchJob.result_text)
        .where(
            ResearchJob.project_id == project_id,
            ResearchJob.status == "completed",
            ResearchJob.result_text.is_not(None),
        )
        .order_by(ResearchJob.id)
    )
    return [SourceItem("job", f"j:{i}", result, research_job_id=i) for i, result in rows]


async def stored_hashes(
    session: AsyncSession,
    project_id: int,
    model: str,
    dimensions: int,
    encoding: str,
    source: str | None = None,
) -> dict[str, dict[int, str]]:
    """``{ref: {chunk_index: text_hash}}`` of the project's chunks for one triple."""
    query = select(EmbeddingChunk.ref, EmbeddingChunk.chunk_index, EmbeddingChunk.text_hash).where(
        EmbeddingChunk.project_id == project_id,
        EmbeddingChunk.model == model,
        EmbeddingChunk.dimensions == dimensions,
        EmbeddingChunk.encoding == encoding,
    )
    if source is not None:
        query = query.where(EmbeddingChunk.source == source)
    out: dict[str, dict[int, str]] = {}
    for ref, index, digest in await session.execute(query):
        out.setdefault(ref, {})[index] = digest
    return out


async def count_for_triple(
    session: AsyncSession, project_id: int, model: str, dimensions: int, encoding: str
) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(EmbeddingChunk)
            .where(
                EmbeddingChunk.project_id == project_id,
                EmbeddingChunk.model == model,
                EmbeddingChunk.dimensions == dimensions,
                EmbeddingChunk.encoding == encoding,
            )
        )
    ).scalar_one()


async def count_by_group(
    session: AsyncSession, project_id: int
) -> list[tuple[str, str, int, str, int]]:
    """``(source, model, dimensions, encoding, chunks)`` for every stored combination."""
    rows = await session.execute(
        select(
            EmbeddingChunk.source,
            EmbeddingChunk.model,
            EmbeddingChunk.dimensions,
            EmbeddingChunk.encoding,
            func.count(),
        )
        .where(EmbeddingChunk.project_id == project_id)
        .group_by(
            EmbeddingChunk.source,
            EmbeddingChunk.model,
            EmbeddingChunk.dimensions,
            EmbeddingChunk.encoding,
        )
        .order_by(
            EmbeddingChunk.source,
            EmbeddingChunk.model,
            EmbeddingChunk.dimensions,
            EmbeddingChunk.encoding,
        )
    )
    return [(s, m, d, e, n) for s, m, d, e, n in rows]


async def delete_item_chunks(
    session: AsyncSession, project_id: int, ref: str, model: str, dimensions: int, encoding: str
) -> int:
    """Remove one item's chunks for one triple (before its changed chunks are stored)."""
    result = await session.execute(
        delete(EmbeddingChunk).where(
            EmbeddingChunk.project_id == project_id,
            EmbeddingChunk.ref == ref,
            EmbeddingChunk.model == model,
            EmbeddingChunk.dimensions == dimensions,
            EmbeddingChunk.encoding == encoding,
        )
    )
    return result.rowcount or 0


_EXISTS = {
    "chat": (
        "EXISTS (SELECT 1 FROM chat_messages m JOIN chats c ON c.id = m.chat_id "
        "WHERE m.id = :chat_message_id AND c.project_id = :project_id)"
    ),
    "job": (
        "EXISTS (SELECT 1 FROM research_jobs j "
        "WHERE j.id = :research_job_id AND j.project_id = :project_id)"
    ),
    "text": "1",
}
_INSERT = (
    "INSERT INTO embedding_chunks (project_id, source, chat_message_id, research_job_id, ref, "
    "chunk_index, text, text_hash, model, dimensions, encoding, vector, created_at) "
    "SELECT :project_id, :source, :chat_message_id, :research_job_id, :ref, :chunk_index, :text, "
    ":text_hash, :model, :dimensions, :encoding, :vector, :created_at WHERE {exists} "
    "ON CONFLICT DO NOTHING RETURNING id"
)


async def insert_chunks(
    session: AsyncSession,
    project_id: int,
    rows: list[ChunkRow],
    *,
    now: datetime | None = None,
) -> tuple[list[int], list[str]]:
    """Store ``rows`` that still have their source: ``(inserted ids, refs whose source is gone)``.

    A chat message or job deleted (or moved out of the project) while a billed request was in
    flight is skipped here instead of failing the foreign key; a chunk that already exists is
    ignored (``ON CONFLICT DO NOTHING``) and is neither inserted nor reported as gone."""
    stamp = now or utcnow()
    inserted: list[int] = []
    gone: list[str] = []
    for row in rows:
        values: dict[str, Any] = {
            "project_id": project_id,
            "source": row.source,
            "chat_message_id": row.chat_message_id,
            "research_job_id": row.research_job_id,
            "ref": row.ref,
            "chunk_index": row.chunk_index,
            "text": row.text,
            "text_hash": row.text_hash,
            "model": row.model,
            "dimensions": row.dimensions,
            "encoding": row.encoding,
            "vector": row.vector,
            "created_at": stamp.strftime("%Y-%m-%d %H:%M:%S.%f"),  # how SQLAlchemy stores it
        }
        if row.source != "text":
            present = await session.execute(
                text(f"SELECT {_EXISTS[row.source]}"),
                {
                    k: values[k]
                    for k in ("project_id", "chat_message_id", "research_job_id")
                    if f":{k}" in _EXISTS[row.source]
                },
            )
            if not present.scalar_one():
                if row.ref not in gone:
                    gone.append(row.ref)
                continue
        result = await session.execute(text(_INSERT.format(exists=_EXISTS[row.source])), values)
        new_id = result.scalar_one_or_none()
        if new_id is not None:
            inserted.append(new_id)
    return inserted, gone


async def candidate_vectors(
    session: AsyncSession,
    project_id: int,
    model: str,
    dimensions: int,
    encoding: str,
    source: str | None = None,
) -> list[tuple[int, bytes]]:
    """``(id, vector)`` of the candidates for a search: ids and vectors ONLY, never the text."""
    query = select(EmbeddingChunk.id, EmbeddingChunk.vector).where(
        EmbeddingChunk.project_id == project_id,
        EmbeddingChunk.model == model,
        EmbeddingChunk.dimensions == dimensions,
        EmbeddingChunk.encoding == encoding,
    )
    if source is not None:
        query = query.where(EmbeddingChunk.source == source)
    return [(i, bytes(v)) for i, v in await session.execute(query.order_by(EmbeddingChunk.id))]


async def hit_details(session: AsyncSession, ids: list[int]) -> dict[int, Hit]:
    """Text and source references of the winning chunks (``chat_id`` by a join on the message)."""
    if not ids:
        return {}
    rows = await session.execute(
        select(
            EmbeddingChunk.id,
            EmbeddingChunk.source,
            EmbeddingChunk.ref,
            EmbeddingChunk.chunk_index,
            EmbeddingChunk.text,
            EmbeddingChunk.chat_message_id,
            EmbeddingChunk.research_job_id,
            ChatMessage.chat_id,
        )
        .outerjoin(ChatMessage, ChatMessage.id == EmbeddingChunk.chat_message_id)
        .where(EmbeddingChunk.id.in_(ids))
    )
    return {r[0]: Hit(*r) for r in rows}


async def delete_chunks(
    session: AsyncSession,
    project_id: int,
    *,
    source: str | None = None,
    model: str | None = None,
    dimensions: int | None = None,
    encoding: str | None = None,
) -> int:
    """Remove the project's chunks matching every given filter (an omitted one matches all)."""
    statement = delete(EmbeddingChunk).where(EmbeddingChunk.project_id == project_id)
    for column, value in (
        (EmbeddingChunk.source, source),
        (EmbeddingChunk.model, model),
        (EmbeddingChunk.dimensions, dimensions),
        (EmbeddingChunk.encoding, encoding),
    ):
        if value is not None:
            statement = statement.where(column == value)
    return (await session.execute(statement)).rowcount or 0

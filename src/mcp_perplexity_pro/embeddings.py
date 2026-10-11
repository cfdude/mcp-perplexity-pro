"""Embeddings API logic for ``perplexity_embed`` (design D1 to D14).

Pure pieces first (decoding, chunking, request building, planning, scoring), then the cost rule
and the operations that use the store and ``costed.costed_call``. Everything that can fail on a
caller's input raises ``PerplexityError("invalid_request", ...)`` naming the option, so a tool
validates first and nothing is sent, recorded or created for a bad call.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from mcp_perplexity_pro import pricing
from mcp_perplexity_pro.agent import _bad, shielded_write
from mcp_perplexity_pro.costed import Costed, Recording, costed_call
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.models import EmbeddingsResponse
from mcp_perplexity_pro.redaction import scrub_secrets
from mcp_perplexity_pro.storage import embeddings as store
from mcp_perplexity_pro.storage.embeddings import ChunkRow
from mcp_perplexity_pro.storage.projects import (
    DEFAULT_PROJECT,
    find_project,
    validate_project_name,
)
from mcp_perplexity_pro.storage.session import unit_of_work
from mcp_perplexity_pro.usage import (
    Usage,
    computed_usage,
    format_usd,
    usage_from_embeddings_response,
)

logger = logging.getLogger(__name__)

TOOL = "perplexity_embed"
SOURCES = ("chat", "job", "text")
MAX_STORED_CHUNKS = 20_000  # per project and (model, dimensions, encoding)
DEFAULT_LIMIT = 256
MAX_LIMIT = 2048
MAX_TEXT_ITEMS = 100
MAX_KEY_CHARS = 128
MAX_ITEM_CHARS = 100_000

MODELS = ("pplx-embed-v1-0.6b", "pplx-embed-v1-4b")
DEFAULT_MODEL = MODELS[0]
FULL_DIMENSIONS = {"pplx-embed-v1-0.6b": 1024, "pplx-embed-v1-4b": 2560}  # the API's own maximum
MIN_DIMENSIONS = 128
MAX_BATCH_INPUTS = 64  # our batch cap; the API allows 512
MAX_BATCH_CHARS = 100_000  # keeps a batch under the 120000-token limit even at 1 token per char
MAX_CHUNK_CHARS = 4000  # our chunk size (about 1000 tokens); the API allows 32K tokens per input
MAX_CHUNKS_PER_TEXT = 50  # our cap: a longer text is cut, with a warning
ENCODINGS = ("int8", "binary")
API_ENCODING = {"int8": "base64_int8", "binary": "base64_binary"}


# --- Decoding (design D8) --------------------------------------------------------------------


def _unreadable(why: str) -> PerplexityError:
    # never echoes the vector string: it is data, and could be large
    return PerplexityError("unexpected_response", f"An embedding could not be decoded: {why}.")


def decode_vector(b64: object, encoding: str, dimensions: int) -> bytes:
    """The bytes of one base64 vector, strictly: ``int8`` is exactly ``dimensions`` bytes and
    ``binary`` exactly ``dimensions / 8`` (``dimensions`` a multiple of 8). The bytes come back
    unchanged. Raises ``unexpected_response`` otherwise."""
    if not isinstance(b64, str):
        raise _unreadable("not a string")
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise _unreadable("not valid base64") from None
    if encoding == "int8":
        expected = dimensions
    elif encoding == "binary":
        if dimensions % 8:
            raise _unreadable("binary vectors need a multiple of 8 dimensions")
        expected = dimensions // 8
    else:
        raise _unreadable("unknown encoding")
    if len(raw) != expected or not raw:
        raise _unreadable(f"expected {expected} bytes, got {len(raw)}")
    return raw


# --- Cost (design D10) -----------------------------------------------------------------------


def embeddings_usage(model: object, raw: object) -> Usage:
    """The usage of one embeddings request: the cost the API reports (source ``reported``);
    else the documented price per token of the model (source ``computed``) when the model is
    priced and ``prompt_tokens`` is a valid count; else unknown (source ``none``), never zero.
    A reported cost is never replaced. Never raises."""
    parsed = usage_from_embeddings_response(raw)
    try:
        if parsed.cost_source == "reported":
            return parsed
        tokens = parsed.input_tokens
        nano = (
            pricing.embeddings_cost_nano(model, tokens)
            if tokens is not None and isinstance(model, str)
            else None
        )
        if nano is None:
            return parsed
        facts: dict[str, Any] = {"input_tokens": tokens, "total_tokens": parsed.total_tokens}
        return computed_usage(nano, raw=parsed.raw, **facts)
    except Exception:
        return parsed


# --- Chunking (design D3) --------------------------------------------------------------------


def is_blank(text: object) -> bool:
    """The one rule for "no text": not a string, or only whitespace (``index`` and ``status``)."""
    return not isinstance(text, str) or not text.strip()


def text_hash(chunk: str) -> str:
    return hashlib.sha256(chunk.encode("utf-8")).hexdigest()


def _cut_point(rest: str) -> int:
    """Where to cut ``rest`` (longer than a chunk): the last blank line, else line break, else
    space inside the limit, else the limit itself."""
    for separator in ("\n\n", "\n", " "):
        at = rest.rfind(separator, 0, MAX_CHUNK_CHARS)
        if at > 0:
            return at
    return MAX_CHUNK_CHARS


def chunk_text(text: str) -> tuple[list[str], bool]:
    """Split ``text`` into chunks of at most 4000 characters, stripped, empty ones dropped, at
    most 50 of them. Returns ``(chunks, cut)`` where ``cut`` says text beyond the 50th chunk was
    ignored. Deterministic: the same text always gives the same chunks."""
    chunks: list[str] = []
    rest = text
    while rest.strip():
        if len(rest) <= MAX_CHUNK_CHARS:
            piece, rest = rest, ""
        else:
            at = _cut_point(rest)
            piece, rest = rest[:at], rest[at:]
        piece = piece.strip()
        if piece:
            chunks.append(piece)
        if len(chunks) >= MAX_CHUNKS_PER_TEXT and rest.strip():
            return chunks, True
    return chunks, False


# --- Request building (design D2) ------------------------------------------------------------


def check_options(model: object, dimensions: object, encoding: object) -> None:
    """Validate the options every action shares. Raises ``invalid_request`` naming the option."""
    if model not in MODELS:
        raise _bad("model", f"must be one of {', '.join(MODELS)}.")
    if dimensions is not None:
        top = FULL_DIMENSIONS[str(model)]
        if (
            isinstance(dimensions, bool)
            or not isinstance(dimensions, int)
            or not MIN_DIMENSIONS <= dimensions <= top
            or dimensions % 8
        ):
            raise _bad(
                "dimensions",
                f"must be a whole number from {MIN_DIMENSIONS} to {top} for {model}, "
                "a multiple of 8.",
            )
    if encoding not in ENCODINGS:
        raise _bad("encoding", f"must be one of {', '.join(ENCODINGS)}.")


def stored_dimensions(model: str, dimensions: int | None) -> int:
    """The size actually returned: the given ``dimensions``, else the model's full size."""
    return dimensions if dimensions is not None else FULL_DIMENSIONS[model]


def build_request(
    model: str, inputs: list[str], *, dimensions: int | None = None, encoding: str = "int8"
) -> dict[str, Any]:
    """Validate and build the ``POST /v1/embeddings`` body. Pure: no network, no database.
    ``model`` and ``encoding_format`` are always sent; ``dimensions`` only when given (the
    model's full size applies otherwise). Raises ``invalid_request`` naming the option."""
    check_options(model, dimensions, encoding)
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= MAX_BATCH_INPUTS:
        raise _bad("input", f"must be a list of 1 to {MAX_BATCH_INPUTS} texts.")
    total = 0
    for text in inputs:
        if not isinstance(text, str) or not text:
            raise _bad("input", "every text must be a non-empty string.")
        if len(text) > MAX_CHUNK_CHARS:
            raise _bad("input", f"every text is at most {MAX_CHUNK_CHARS} characters.")
        total += len(text)
    if total > MAX_BATCH_CHARS:
        raise _bad("input", f"a request holds at most {MAX_BATCH_CHARS} characters in all.")
    request: dict[str, Any] = {"model": model, "input": list(inputs)}
    if dimensions is not None:
        request["dimensions"] = dimensions
    request["encoding_format"] = API_ENCODING[encoding]
    return request


# --- Planning an index call (design D6) ------------------------------------------------------


@dataclass(frozen=True)
class PlannedChunk:
    item: int  # position of the chunk's item in the planner's input
    chunk_index: int
    text: str


@dataclass(frozen=True)
class IndexPlan:
    batches: list[list[PlannedChunk]]
    taken_items: int  # how many leading items are in the plan
    remaining: int  # pending chunks of the items NOT taken


def plan_index(items: Sequence[Sequence[str]], limit: int) -> IndexPlan:
    """Plan one ``index`` call over the pending items' chunks (each item a non-empty list).

    Items are taken whole, in order, and the call stops after the item that makes the running
    chunk count reach ``limit``; at least one whole item is always taken, so a caller looping on
    ``remaining`` always makes progress (a call may exceed ``limit`` by up to 49 chunks). The
    taken chunks are packed in order into batches of at most 64 inputs and 100000 characters.
    """
    taken = 0
    count = 0
    for chunks in items:
        taken += 1
        count += len(chunks)
        if count >= limit:
            break
    batches: list[list[PlannedChunk]] = []
    current: list[PlannedChunk] = []
    chars = 0
    for position, chunks in enumerate(items[:taken]):
        for chunk_index, text in enumerate(chunks):
            if current and (
                len(current) >= MAX_BATCH_INPUTS or chars + len(text) > MAX_BATCH_CHARS
            ):
                batches.append(current)
                current, chars = [], 0
            current.append(PlannedChunk(position, chunk_index, text))
            chars += len(text)
    if current:
        batches.append(current)
    remaining = sum(len(chunks) for chunks in items[taken:])
    return IndexPlan(batches, taken, remaining)


# --- The one costed call (design D10, D11) ---------------------------------------------------


async def run_embed(
    app: Any, *, project: str | None, body: dict[str, Any], model: str
) -> Costed[EmbeddingsResponse]:
    """Send ``body`` and record the request (``costed.costed_call``)."""

    def interpret(response: EmbeddingsResponse) -> Recording:
        answered = response.model if isinstance(response.model, str) else None
        return Recording(
            status="ok",
            usage=embeddings_usage(answered or model, response.usage),
            model=answered,
        )

    return await costed_call(
        app,
        tool=TOOL,
        api="embeddings",
        project=project,
        preset=None,
        call=lambda: app.client.embed(body),
        record=interpret,
    )


# --- One in-process lock per project (design D7) ---------------------------------------------


class ProjectLocks:
    """One ``asyncio.Lock`` per project name, created on demand and dropped when unused (the
    ``JobLocks`` pattern). ``index`` and ``delete`` hold it so two calls on one project do not
    embed the same pending items twice."""

    def __init__(self) -> None:
        self._held: dict[str, list[Any]] = {}

    @asynccontextmanager
    async def hold(self, name: str) -> AsyncIterator[None]:
        entry = self._held.get(name)
        if entry is None:
            entry = self._held[name] = [asyncio.Lock(), 0]
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                del self._held[name]


# --- Index (design D5 to D7, D12) ------------------------------------------------------------


@dataclass
class IndexResult:
    embedded_chunks: int = 0
    embedded_items: int = 0
    skipped_items: int = 0  # unchanged, or whose source vanished during the call
    remaining: int = 0
    requests: int = 0
    input_tokens: int = 0
    cost_nano: int = 0
    costs_known: int = 0
    calls_cost_unknown: int = 0
    sources: set[str] = field(default_factory=set)
    latency_ms: int = 0
    warnings: list[str] = field(default_factory=list)

    def add_usage(self, usage: Usage | Any) -> None:
        if isinstance(usage, Usage):
            if usage.input_tokens:
                self.input_tokens += usage.input_tokens
            if usage.cost_source != "none":
                self.cost_nano += usage.cost_nano_usd
                self.costs_known += 1
                self.sources.add(usage.cost_source)
                return
        self.calls_cost_unknown += 1

    @property
    def cost_source(self) -> str:
        if not self.sources:
            return "none"
        return next(iter(self.sources)) if len(self.sources) == 1 else "mixed"

    @property
    def cost_usd(self) -> str | None:
        return format_usd(self.cost_nano) if self.sources else None


@dataclass
class _Pending:
    ref: str
    source: str
    chunks: list[str]
    hashes: list[str]
    replace: bool  # it has (changed) stored chunks for this triple
    chat_message_id: int | None = None
    research_job_id: int | None = None
    vectors: dict[int, bytes] = field(default_factory=dict)


def check_index_arguments(source: object, items: object, limit: object) -> list[tuple[str, str]]:
    """Validate ``source``, ``items`` and ``limit``; returns the ``(key, text)`` pairs of a
    ``text`` source (empty for the others). Raises ``invalid_request``."""
    if source not in SOURCES:
        raise _bad("source", f"must be one of {', '.join(SOURCES)}.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise _bad("limit", f"must be a whole number from 1 to {MAX_LIMIT}.")
    if source != "text":
        if items:
            raise _bad("items", "is only for the text source.")
        return []
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_TEXT_ITEMS:
        raise _bad("items", f"a text index needs 1 to {MAX_TEXT_ITEMS} items.")
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise _bad("items", "each item is an object with a key and a text.")
        key, body = item.get("key"), item.get("text")
        if is_blank(key) or len(key) > MAX_KEY_CHARS:
            raise _bad(
                "items", f"each key is non-blank text of at most {MAX_KEY_CHARS} characters."
            )
        if key in seen:
            raise _bad("items", "a key is repeated in one call.")
        if is_blank(body) or len(body) > MAX_ITEM_CHARS:
            raise _bad("items", f"each text is non-blank and at most {MAX_ITEM_CHARS} characters.")
        seen.add(key)
        pairs.append((key, body))
    return pairs


def _pending_item(
    ref: str, source: str, body: str, stored: dict[str, dict[int, str]], **keys: int | None
) -> tuple[_Pending | None, bool]:
    """``(pending or None when current, cut)`` for one item against its stored hashes."""
    chunks, cut = chunk_text(body)
    hashes = [text_hash(c) for c in chunks]
    have = stored.get(ref)
    if have is not None and have == dict(enumerate(hashes)):
        return None, cut
    if not chunks:
        return None, cut
    return _Pending(ref, source, chunks, hashes, have is not None, **keys), cut


async def _gather(
    app: Any,
    project_name: str,
    source: str,
    pairs: list[tuple[str, str]],
    triple: tuple[str, int, str],
    result: IndexResult,
) -> tuple[list[_Pending], int | None, int]:
    """The pending items of one call: ``(pending, project_id or None, stored chunk count)``."""
    async with unit_of_work(app.engine, write=False) as session:
        project = await find_project(session, project_name)
        pid = project.id if project is not None else None
        stored = await store.stored_hashes(session, pid, *triple, source=source) if pid else {}
        total = await store.count_for_triple(session, pid, *triple) if pid else 0
        pending: list[_Pending] = []
        cut_items = 0
        if source == "text":
            candidates = [(f"t:{key}", body, {}) for key, body in pairs]
        elif pid is None:
            candidates = []  # nothing of a project that does not exist can be indexed
        else:
            items = await store.source_items(session, pid, source)
            candidates = [
                (
                    i.ref,
                    i.text,
                    {"chat_message_id": i.chat_message_id, "research_job_id": i.research_job_id},
                )
                for i in items
                if not is_blank(i.text)
            ]
    for ref, body, keys in candidates:
        item, cut = _pending_item(ref, source, body, stored, **keys)
        cut_items += 1 if cut else 0
        if item is None:
            result.skipped_items += 1
        else:
            pending.append(item)
    if cut_items:
        result.warnings.append(
            f"{cut_items} text(s) were longer than {MAX_CHUNKS_PER_TEXT} chunks; "
            "the rest of each was not indexed."
        )
    return pending, pid, total


def _decode_batch(
    response: EmbeddingsResponse, count: int, encoding: str, dimensions: int
) -> list[bytes]:
    """The decoded vectors of a response, in input order. Raises ``unexpected_response`` when the
    data does not hold exactly one valid vector per input."""
    data = response.data
    if len(data) != count:
        raise PerplexityError(
            "unexpected_response", f"The API returned {len(data)} embeddings for {count} inputs."
        )
    vectors: dict[int, bytes] = {}
    for entry in data:
        index = entry.get("index") if isinstance(entry, dict) else None
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count:
            raise PerplexityError("unexpected_response", "An embedding has an invalid index.")
        if index in vectors:
            raise PerplexityError("unexpected_response", "An embedding index is repeated.")
        vectors[index] = decode_vector(entry.get("embedding"), encoding, dimensions)
    return [vectors[i] for i in range(count)]


async def _write_complete_items(
    app: Any,
    project_name: str,
    items: list[_Pending],
    triple: tuple[str, int, str],
    result: IndexResult,
) -> None:
    """Store the items whose chunks are all embedded, in one unit: only what still exists."""
    model, dimensions, encoding = triple
    async with unit_of_work(app.engine) as session:
        project = await find_project(session, project_name)  # by NAME: it may have been recreated
        if project is None:
            result.skipped_items += len(items)
            result.warnings.append("The project was deleted during the call; nothing was stored.")
            return
        rows: list[ChunkRow] = []
        for item in items:
            if item.replace:
                await store.delete_item_chunks(session, project.id, item.ref, *triple)
            rows += [
                ChunkRow(
                    source=item.source,
                    ref=item.ref,
                    chunk_index=i,
                    text=item.chunks[i],
                    text_hash=item.hashes[i],
                    model=model,
                    dimensions=dimensions,
                    encoding=encoding,
                    vector=item.vectors[i],
                    chat_message_id=item.chat_message_id,
                    research_job_id=item.research_job_id,
                )
                for i in range(len(item.chunks))
            ]
        inserted, gone = await store.insert_chunks(session, project.id, rows)
    result.embedded_chunks += len(inserted)
    result.embedded_items += len(items) - len(gone)
    if gone:
        result.skipped_items += len(gone)
        result.warnings.append(
            f"{len(gone)} item(s) were deleted during the call and were not stored."
        )


async def index(
    app: Any,
    *,
    project: str | None,
    source: str,
    items: list[Any] | None,
    model: str,
    dimensions: int | None,
    encoding: str,
    limit: int,
) -> IndexResult:
    """Embed and store the pending items of ``source`` (design D5 to D7, D12)."""
    check_options(model, dimensions, encoding)
    pairs = check_index_arguments(source, items, limit)
    name = validate_project_name(project or DEFAULT_PROJECT)
    size = stored_dimensions(model, dimensions)
    triple = (model, size, encoding)
    result = IndexResult()
    async with app.embed_locks.hold(name):
        pending, _, stored_total = await _gather(app, name, source, pairs, triple, result)
        plan = plan_index([p.chunks for p in pending], limit)
        taken = pending[: plan.taken_items]
        if stored_total + sum(len(p.chunks) for p in taken) > MAX_STORED_CHUNKS:
            raise _bad(
                "limit",
                f"this would pass {MAX_STORED_CHUNKS} stored chunks for this model, size and "
                "encoding; delete some first.",
            )
        result.remaining = plan.remaining
        for batch in plan.batches:
            inputs = [c.text for c in batch]
            body = build_request(model, inputs, dimensions=dimensions, encoding=encoding)
            try:
                costed = await run_embed(app, project=name, body=body, model=model)
                vectors = _decode_batch(costed.result, len(inputs), encoding, size)
            except PerplexityError as exc:
                raise PerplexityError(
                    exc.category,
                    f"{exc} ({result.embedded_chunks} chunks were stored before this failure.)",
                ) from exc
            result.requests += 1
            result.latency_ms += costed.latency_ms
            result.add_usage(None if costed.recording is None else costed.recording.usage)
            complete: list[_Pending] = []
            for planned, vector in zip(batch, vectors, strict=True):
                item = taken[planned.item]
                item.vectors[planned.chunk_index] = vector
                if len(item.vectors) == len(item.chunks) and item not in complete:
                    complete.append(item)
            await shielded_write(_write_complete_items(app, name, complete, triple, result))
    return result


# --- Scoring (design D9) ---------------------------------------------------------------------

BLOCK_ROWS = 2048
_POPCOUNT: Any = None


def _popcount_table() -> Any:
    global _POPCOUNT
    if _POPCOUNT is None:
        import numpy as np

        _POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint16)
    return _POPCOUNT


def cosine_scores(query: bytes, matrix: Any) -> Any:
    """Cosine similarity of ``query`` (int8 bytes) against each row of ``matrix`` (an ``N x D``
    int8 array), read as signed integers in float32. A zero vector scores 0."""
    import numpy as np

    q = np.frombuffer(query, dtype=np.int8).astype(np.float32)
    m = matrix.astype(np.float32)
    dots = m @ q
    norms = np.linalg.norm(m, axis=1) * np.linalg.norm(q)
    scores = np.where(norms == 0, 0.0, dots / np.where(norms == 0, 1.0, norms))
    return np.clip(scores, -1.0, 1.0)


def hamming_scores(query: bytes, matrix: Any, dimensions: int) -> Any:
    """``1 - hamming distance / dimensions`` of ``query`` (packed bits) against each row of
    ``matrix`` (an ``N x dimensions/8`` uint8 array)."""
    import numpy as np

    q = np.frombuffer(query, dtype=np.uint8)
    distances = _popcount_table()[np.bitwise_xor(matrix, q)].sum(axis=1)
    return 1.0 - distances / float(dimensions)


def top_k(
    query: bytes,
    rows: Sequence[tuple[int, bytes]],
    *,
    k: int,
    encoding: str,
    dimensions: int,
    min_score: float | None = None,
) -> list[tuple[int, float]]:
    """The best ``k`` ``(chunk id, score)`` of ``rows`` (``(id, vector bytes)``), best first, ties
    broken by ascending id. Scores in blocks of 2048 rows so memory stays small; blocking changes
    nothing about the result. CPU-bound: call it under ``asyncio.to_thread``."""
    import numpy as np

    width = dimensions if encoding == "int8" else dimensions // 8
    dtype = np.int8 if encoding == "int8" else np.uint8
    best_ids: list[Any] = []
    best_scores: list[Any] = []
    for start in range(0, len(rows), BLOCK_ROWS):
        block = rows[start : start + BLOCK_ROWS]
        matrix = np.frombuffer(b"".join(v for _, v in block), dtype=dtype).reshape(-1, width)
        scores = (
            cosine_scores(query, matrix)
            if encoding == "int8"
            else hamming_scores(query, matrix, dimensions)
        )
        ids = np.array([i for i, _ in block], dtype=np.int64)
        order = np.lexsort((ids, -scores))[:k]
        best_ids.append(ids[order])
        best_scores.append(scores[order])
    if not best_ids:
        return []
    ids = np.concatenate(best_ids)
    scores = np.concatenate(best_scores)
    order = np.lexsort((ids, -scores))[:k]
    out = [(int(ids[i]), float(scores[i])) for i in order]
    return [(i, s) for i, s in out if min_score is None or s >= min_score]


# --- Search (design D9) ----------------------------------------------------------------------

MAX_QUERY_CHARS = 4000
MAX_TOP_K = 20
HIT_TEXT_CHARS = 800


@dataclass
class SearchHit:
    score: float
    source: str
    chunk_index: int
    text: str
    chat_id: int | None = None
    message_id: int | None = None
    job_id: int | None = None
    key: str | None = None


@dataclass
class SearchResult:
    hits: list[SearchHit] = field(default_factory=list)
    candidates: int = 0
    requests: int = 0
    input_tokens: int = 0
    cost: IndexResult = field(default_factory=IndexResult)  # the cost tally of the one request
    latency_ms: int = 0
    warnings: list[str] = field(default_factory=list)


def check_search_arguments(
    query: object, top_k_value: object, min_score: object, source: object
) -> None:
    if is_blank(query) or len(query) > MAX_QUERY_CHARS:  # type: ignore[arg-type]
        raise _bad("query", f"must be non-blank text of at most {MAX_QUERY_CHARS} characters.")
    if (
        isinstance(top_k_value, bool)
        or not isinstance(top_k_value, int)
        or not 1 <= top_k_value <= MAX_TOP_K
    ):
        raise _bad("top_k", f"must be a whole number from 1 to {MAX_TOP_K}.")
    if min_score is not None and (
        isinstance(min_score, bool)
        or not isinstance(min_score, int | float)
        or not -1.0 <= min_score <= 1.0
    ):
        raise _bad("min_score", "must be a number from -1 to 1.")
    if source is not None and source not in SOURCES:
        raise _bad("source", f"must be one of {', '.join(SOURCES)}.")


def _hit(score: float, detail: store.Hit, secrets: tuple[str, ...]) -> SearchHit:
    body = scrub_secrets(detail.text, secrets)[:HIT_TEXT_CHARS]
    hit = SearchHit(score=score, source=detail.source, chunk_index=detail.chunk_index, text=body)
    if detail.source == "chat":
        hit.chat_id, hit.message_id = detail.chat_id, detail.chat_message_id
    elif detail.source == "job":
        hit.job_id = detail.research_job_id
    else:
        hit.key = detail.ref[2:]
    return hit


async def search(
    app: Any,
    *,
    project: str | None,
    query: str,
    top_k_value: int,
    min_score: float | None,
    source: str | None,
    model: str,
    dimensions: int | None,
    encoding: str,
) -> SearchResult:
    """Embed ``query`` once and rank the project's stored chunks of the same triple."""
    check_options(model, dimensions, encoding)
    check_search_arguments(query, top_k_value, min_score, source)
    name = validate_project_name(project or DEFAULT_PROJECT)
    size = stored_dimensions(model, dimensions)
    result = SearchResult()
    async with unit_of_work(app.engine, write=False) as session:
        found = await find_project(session, name)
        candidates = (
            await store.candidate_vectors(session, found.id, model, size, encoding, source)
            if found is not None
            else []
        )
    result.candidates = len(candidates)
    if not candidates:
        result.warnings.append("Nothing is indexed for this project, model, size and encoding.")
        return result
    body = build_request(model, [query], dimensions=dimensions, encoding=encoding)
    costed = await run_embed(app, project=name, body=body, model=model)
    (vector,) = _decode_batch(costed.result, 1, encoding, size)
    result.requests = 1
    result.latency_ms = costed.latency_ms
    result.cost.add_usage(None if costed.recording is None else costed.recording.usage)
    result.input_tokens = result.cost.input_tokens
    best = await asyncio.to_thread(
        top_k,
        vector,
        candidates,
        k=top_k_value,
        encoding=encoding,
        dimensions=size,
        min_score=min_score,
    )
    async with unit_of_work(app.engine, write=False) as session:
        details = await store.hit_details(session, [i for i, _ in best])
    secrets = (app.settings.api_key.get_secret_value(),)
    result.hits = [_hit(score, details[i], secrets) for i, score in best if i in details]
    return result

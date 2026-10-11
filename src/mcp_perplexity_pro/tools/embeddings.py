"""``perplexity_embed``: index saved text as vectors and search it by meaning (embeddings-tool)."""

import time
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_perplexity_pro import embeddings as emb
from mcp_perplexity_pro.errors import PerplexityError

ACTIONS = ("index", "search", "status", "delete")


class HitOut(BaseModel):
    score: Annotated[float, Field(description="Similarity: cosine (int8) or 1 - hamming (binary)")]
    source: Annotated[str, Field(description="chat, job or text")]
    chunk_index: Annotated[int, Field(description="Which chunk of its source item")]
    text: Annotated[str, Field(description="The chunk text, cut to 800 characters")]
    chat_id: int | None = None
    message_id: int | None = None
    job_id: int | None = None
    key: str | None = None


class GroupOut(BaseModel):
    source: str
    model: str
    dimensions: int
    encoding: str
    chunks: int


class EmbedOutput(BaseModel):
    action: Annotated[str, Field(description="index, search, status or delete")]
    project: Annotated[str, Field(description="The project the call used")]
    warnings: Annotated[list[str], Field(description="Things worth knowing about this result")]
    latency_ms: Annotated[int, Field(description="Measured wall time of the upstream calls")] = 0
    embedded_chunks: Annotated[int | None, Field(description="index: chunks stored")] = None
    embedded_items: Annotated[int | None, Field(description="index: items stored")] = None
    skipped_items: Annotated[
        int | None, Field(description="index: items unchanged or gone during the call")
    ] = None
    remaining: Annotated[int | None, Field(description="index: pending chunks left")] = None
    requests: Annotated[int | None, Field(description="index, search: upstream requests")] = None
    input_tokens: Annotated[int | None, Field(description="index, search: tokens billed")] = None
    cost_usd: Annotated[
        str | None, Field(description="index, search: exact USD cost as a decimal string")
    ] = None
    cost_source: Annotated[
        str | None, Field(description="reported, computed, mixed or none (unknown)")
    ] = None
    calls_cost_unknown: Annotated[int | None, Field(description="requests with unknown cost")] = (
        None
    )
    candidates: Annotated[int | None, Field(description="search: stored chunks compared")] = None
    hits: Annotated[list[HitOut] | None, Field(description="search: best chunks first")] = None
    groups: Annotated[
        list[GroupOut] | None, Field(description="status: stored chunks per combination")
    ] = None
    unindexed_chat: Annotated[int | None, Field(description="status: chat messages left")] = None
    unindexed_job: Annotated[int | None, Field(description="status: completed jobs left")] = None
    removed: Annotated[int | None, Field(description="delete: chunks removed")] = None


def render(out: EmbedOutput) -> str:
    lines = [f"Warning: {w}" for w in out.warnings]
    if out.action == "index":
        lines.append(
            f"Indexed {out.embedded_chunks} chunks of {out.embedded_items} items "
            f"({out.skipped_items} skipped, {out.remaining} chunks remaining) in "
            f"{out.requests} request(s)."
        )
    elif out.action == "search":
        for i, h in enumerate(out.hits or [], 1):
            ref = h.key or (f"job {h.job_id}" if h.job_id else f"chat {h.chat_id} #{h.message_id}")
            lines.append(f"{i}. [{h.score:.4f}] {h.source} {ref}\n   {h.text[:200]}")
        if not out.hits:
            lines.append("No hits.")
    elif out.action == "status":
        for g in out.groups or []:
            lines.append(f"{g.source}: {g.chunks} chunks ({g.model}, {g.dimensions}, {g.encoding})")
        lines.append(f"Not indexed: {out.unindexed_chat} chat messages, {out.unindexed_job} jobs.")
    else:
        lines.append(f"Removed {out.removed} chunks.")
    if out.cost_source is not None:
        cost = f"cost {out.cost_usd} USD ({out.cost_source})" if out.cost_usd else "cost unknown"
        lines.append(f"Usage: {out.input_tokens} tokens, {cost}, project {out.project}.")
    return "\n".join(lines)


def register(server: FastMCP) -> None:
    @server.tool(
        name=emb.TOOL,
        output_schema=EmbedOutput.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
    )
    async def perplexity_embed(
        ctx: Context,
        action: Annotated[str, Field(description="index, search, status or delete")],
        source: Annotated[
            str | None,
            Field(
                description="chat (saved chat messages), job (completed research reports) or text "
                "(your items). Required for index; filters search and delete"
            ),
        ] = None,
        items: Annotated[
            list[dict[str, Any]] | None,
            Field(
                description="index of source text: 1 to 100 items {key, text}; a key indexed "
                "again with new text replaces its chunks"
            ),
        ] = None,
        query: Annotated[
            str | None, Field(description="search: the text to look for (at most 4000 characters)")
        ] = None,
        top_k: Annotated[int, Field(description="search: results, 1 to 20")] = 5,
        min_score: Annotated[
            float | None, Field(description="search: only scores at or above this, -1 to 1")
        ] = None,
        limit: Annotated[
            int,
            Field(description="index: stop after the item reaching this many new chunks (1-2048)"),
        ] = emb.DEFAULT_LIMIT,
        model: Annotated[
            str | None,
            Field(
                description="pplx-embed-v1-0.6b (default) or pplx-embed-v1-4b; omitted on delete "
                "means every model"
            ),
        ] = None,
        dimensions: Annotated[
            int | None,
            Field(
                description="Vector size, a multiple of 8: 128 to 1024 (0.6b) or 2560 (4b); "
                "omitted is the model's full size (omitted on delete: every size)"
            ),
        ] = None,
        encoding: Annotated[
            str | None,
            Field(description="int8 (default) or binary (32x smaller); omitted on delete: both"),
        ] = None,
        project: Annotated[
            str | None, Field(description="Project the vectors belong to (default: default)")
        ] = None,
        confirm: Annotated[bool, Field(description="delete: must be true")] = False,
    ) -> ToolResult:
        """Index your saved chats, completed research reports or texts as vectors and search them
        by meaning. index SENDS the text it indexes to Perplexity (search sends only the query);
        vectors are stored locally per project and are never returned. Prices per million tokens:
        $0.004 for pplx-embed-v1-0.6b, $0.03 for pplx-embed-v1-4b (the reported cost is
        recorded; see perplexity_usage). An unchanged item is never embedded twice; index stops
        after about `limit` new chunks and reports `remaining`, so call it again until 0. status
        shows what is stored and what is not; delete removes vectors (confirm true). Deleting a
        chat or a project removes its vectors."""
        app = ctx.lifespan_context
        if action not in ACTIONS:
            raise PerplexityError(
                "invalid_request", f"action: must be one of {', '.join(ACTIONS)}."
            )
        started = time.monotonic()
        name = project or "default"
        chosen_model = model if model is not None else emb.DEFAULT_MODEL
        chosen_encoding = encoding if encoding is not None else "int8"
        if action == "index":
            r = await emb.index(
                app,
                project=project,
                source=source,  # type: ignore[arg-type]
                items=items,
                model=chosen_model,
                dimensions=dimensions,
                encoding=chosen_encoding,
                limit=limit,
            )
            out = EmbedOutput(
                action=action,
                project=name,
                warnings=r.warnings,
                latency_ms=r.latency_ms,
                embedded_chunks=r.embedded_chunks,
                embedded_items=r.embedded_items,
                skipped_items=r.skipped_items,
                remaining=r.remaining,
                requests=r.requests,
                input_tokens=r.input_tokens,
                cost_usd=r.cost_usd,
                cost_source=r.cost_source if r.requests else None,  # no request, no cost
                calls_cost_unknown=r.calls_cost_unknown,
            )
        elif action == "search":
            s = await emb.search(
                app,
                project=project,
                query=query,  # type: ignore[arg-type]
                top_k_value=top_k,
                min_score=min_score,
                source=source,
                model=chosen_model,
                dimensions=dimensions,
                encoding=chosen_encoding,
            )
            out = EmbedOutput(
                action=action,
                project=name,
                warnings=s.warnings,
                latency_ms=s.latency_ms,
                requests=s.requests,
                input_tokens=s.input_tokens,
                cost_usd=s.cost.cost_usd,
                cost_source=s.cost.cost_source if s.requests else None,
                calls_cost_unknown=s.cost.calls_cost_unknown,
                candidates=s.candidates,
                hits=[HitOut(**h.__dict__) for h in s.hits],
            )
        elif action == "status":
            st = await emb.status(
                app,
                project=project,
                model=chosen_model,
                dimensions=dimensions,
                encoding=chosen_encoding,
            )
            out = EmbedOutput(
                action=action,
                project=name,
                warnings=[],
                groups=[
                    GroupOut(source=g[0], model=g[1], dimensions=g[2], encoding=g[3], chunks=g[4])
                    for g in st.groups
                ],
                unindexed_chat=st.unindexed_chat,
                unindexed_job=st.unindexed_job,
            )
        else:
            removed = await emb.delete(
                app,
                project=project,
                source=source,
                model=model,
                dimensions=dimensions,
                encoding=encoding,
                confirm=confirm,
            )
            out = EmbedOutput(action=action, project=name, warnings=[], removed=removed)
        if not out.latency_ms:
            out.latency_ms = (
                round((time.monotonic() - started) * 1000) if action in ("status", "delete") else 0
            )
        return ToolResult(content=render(out), structured_content=out.model_dump(mode="json"))

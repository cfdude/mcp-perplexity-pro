"""Task 9.3 (py-embeddings): the logging rule for the embeddings tool
(``docs/lessons/framework-logs-carry-bound-parameters.md``).

``index`` stores text and vectors, so the rule is sharper here: no text, query, vector or base64
string reaches a log. The client logs method, path, status and request id; a failing chunk
insert logs the failure, not the request or the vectors.

Mutation check: adding a log call that interpolates the request body to
``PerplexityClient.embed`` turns every test here red.
"""

import logging

import httpx2
from agent_support import make_world
from embeddings_support import embed_response
from sqlalchemy import text

TOOL = "perplexity_embed"
STATE = "zq-distinctive-embedded-text-5521"
ITEMS = [{"key": "k", "text": STATE}]


def own_log(caplog) -> str:
    fmt = logging.Formatter()
    return "\n".join(
        fmt.format(r) for r in caplog.records if r.name.startswith("mcp_perplexity_pro")
    )


async def test_a_forced_chunk_insert_failure_logs_without_the_text_or_any_vector(
    make_settings, caplog
):
    w = await make_world(make_settings, lambda request, n: embed_response(request))
    try:
        async with w.engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TRIGGER veto_chunk BEFORE INSERT ON embedding_chunks "
                    "BEGIN SELECT RAISE(ABORT, 'vetoed'); END"
                )
            )
        with caplog.at_level(logging.DEBUG):
            result = await w.call(TOOL, action="index", source="text", items=ITEMS, dimensions=128)
        assert result.is_error  # the chunk write failed; the event was recorded first
        assert await w.count("usage_events") == 1 and await w.count("embedding_chunks") == 0
        logged = own_log(caplog)
        assert STATE not in logged and "[parameters" not in logged
        assert "ugYA" not in logged  # no base64 vector text
    finally:
        await w.aclose()


async def test_a_failed_request_log_holds_method_path_and_status_only(make_settings, caplog):
    w = await make_world(
        make_settings, lambda request, n: httpx2.Response(503, json={"error": {"message": "down"}})
    )
    try:
        with caplog.at_level(logging.DEBUG):
            result = await w.call(TOOL, action="index", source="text", items=ITEMS, dimensions=128)
        assert result.is_error
        logged = own_log(caplog)
        assert "/v1/embeddings" in logged and "503" in logged
        assert STATE not in logged and "base64_int8" not in logged
        calls = [r for r in caplog.records if r.name == "mcp_perplexity_pro.client"]
        assert calls and all(
            getattr(r, "http_method", None) == "POST"
            and getattr(r, "http_path", None) == "/v1/embeddings"
            for r in calls
        )
    finally:
        await w.aclose()


async def test_a_successful_index_and_search_log_no_text_query_or_vector(make_settings, caplog):
    w = await make_world(make_settings, lambda request, n: embed_response(request))
    try:
        with caplog.at_level(logging.DEBUG):
            await w.call(TOOL, action="index", source="text", items=ITEMS, dimensions=128)
            await w.call(TOOL, action="search", query="zq-distinctive-query-8812", dimensions=128)
        logged = own_log(caplog)
        assert STATE not in logged and "zq-distinctive-query" not in logged
    finally:
        await w.aclose()

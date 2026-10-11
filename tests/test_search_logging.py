"""Task 5.3 (py-search-api): the logging rule for the search tool
(``docs/lessons/framework-logs-carry-bound-parameters.md``).

A search stores no content, so only its usage event is written, and the query and the snippets
never reach a log: the client logs method, path, status and request id; a failing event insert
logs the failure, not the request.

Mutation check: adding a log call that interpolates the request body to ``PerplexityClient.search``
turns ``test_a_failed_search_log_holds_method_path_and_status_only`` red.
"""

import logging

import httpx2
from agent_support import fixture, make_world, respond_body, respond_with
from sqlalchemy import text

TOOL = "perplexity_search"
QUERY = "zq-distinctive-logged-query-5521"
SNIPPET = "zq-distinctive-snippet-text-9983"


def own_log(caplog) -> str:
    fmt = logging.Formatter()
    return "\n".join(
        fmt.format(r) for r in caplog.records if r.name.startswith("mcp_perplexity_pro")
    )


async def test_a_forced_event_insert_failure_logs_without_the_query_or_any_snippet(
    make_settings, caplog
):
    body = fixture("search_fast_single.json")
    body["results"][0]["snippet"] = SNIPPET
    w = await make_world(make_settings, respond_body(body))
    try:
        async with w.engine.begin() as conn:
            await conn.execute(
                text(
                    "CREATE TRIGGER veto_usage BEFORE INSERT ON usage_events "
                    "BEGIN SELECT RAISE(ABORT, 'vetoed'); END"
                )
            )
        with caplog.at_level(logging.DEBUG):
            result = await w.call(TOOL, query=QUERY)
        assert not result.is_error and SNIPPET in result.content[0].text  # the call still works
        assert await w.count("usage_events") == 0
        logged = own_log(caplog)
        assert "usage event not recorded" in logged  # the failure is logged ...
        assert QUERY not in logged and SNIPPET not in logged  # ... without the content
        assert "[parameters" not in logged
    finally:
        await w.aclose()


async def test_a_failed_search_log_holds_method_path_and_status_only(make_settings, caplog):
    w = await make_world(make_settings, respond_with("search_too_many_queries_400.json", 400))
    try:
        with caplog.at_level(logging.DEBUG):
            result = await w.call(TOOL, query=QUERY)
        assert result.is_error
        logged = own_log(caplog)
        assert "/search" in logged and "400" in logged
        assert QUERY not in logged and "search_type" not in logged
        calls = [r for r in caplog.records if r.name == "mcp_perplexity_pro.client"]
        assert calls and all(
            getattr(r, "http_method", None) == "POST" and getattr(r, "http_path", None) == "/search"
            for r in calls
        )
    finally:
        await w.aclose()


async def test_a_503_log_never_carries_the_request_body(make_settings, caplog):
    w = await make_world(
        make_settings, lambda request, n: httpx2.Response(503, json={"error": {"message": "down"}})
    )
    try:
        with caplog.at_level(logging.DEBUG):
            await w.call(TOOL, query=QUERY, domains=["python.org"])
        logged = own_log(caplog)
        assert QUERY not in logged and "python.org" not in logged
    finally:
        await w.aclose()

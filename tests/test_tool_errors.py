"""Tool error contract: every failure reaches the client as a categorized error, with no leaks."""

import json
import logging

import httpx2
import pytest
from fastmcp import Client, Context
from fastmcp.exceptions import ToolError
from server_support import INITIALIZE, free_port, rpc, serving
from sqlalchemy.exc import OperationalError

from mcp_perplexity_pro.errors import ALL_CATEGORIES, PerplexityError
from mcp_perplexity_pro.log_setup import configure_logging
from mcp_perplexity_pro.server import GENERIC_MESSAGE, build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

KEY = "pplx-" + "Zy9_" * 8  # key-shaped, so both the exact key and the shape rule are exercised
OTHER_TOKEN = "pplx-" + "Qq7-" * 8  # key-shaped but not the configured key
SPEC_VOCABULARY = {
    "invalid_request",
    "authentication",
    "forbidden",
    "not_found",
    "rate_limited",
    "upstream_failure",
    "network_timeout",
    "unexpected_response",
    "confirmation_required",
    "storage_busy",
    "internal_error",
}


@pytest.fixture(autouse=True)
def restore_logging():
    root = logging.getLogger()
    fastmcp = logging.getLogger("fastmcp")
    saved = (list(root.handlers), root.level, list(fastmcp.handlers), fastmcp.propagate)
    yield
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    fastmcp.handlers[:] = saved[2]
    fastmcp.propagate = saved[3]


def echo_key_401(request: httpx2.Request) -> httpx2.Response:
    body = {
        "error": {
            "message": f"Invalid API key {KEY} (also saw {OTHER_TOKEN})",
            "type": "invalid_api_key",
            "code": 401,
        }
    }
    return httpx2.Response(401, json=body)


@pytest.fixture
async def server_and_settings(make_settings):
    settings = make_settings(api_key=KEY)
    migrate(settings)
    engine = create_engine_for(settings)
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(echo_key_401))
    server = build_server(settings, http, engine)

    @server.tool
    async def call_upstream(ctx: Context) -> str:
        return str(await ctx.lifespan_context.client.request_json("GET", "/v1/anything"))

    @server.tool
    async def explode() -> str:
        raise RuntimeError(f"password={KEY} and {OTHER_TOKEN} in /secret/path.py")

    @server.tool
    async def plain_tool_error() -> str:
        raise ToolError(f"hand-written text with {KEY}")

    @server.tool
    async def database_locked() -> str:
        raise OperationalError("UPDATE x", {}, Exception("database is locked"))

    @server.tool
    async def raise_category(category: str) -> str:
        raise PerplexityError(category, f"failure in {category} with {KEY}")

    @server.tool
    async def needs_int(n: int) -> str:
        return str(n)

    yield server, settings
    await http.aclose()
    await engine.dispose()


async def call(server, name, arguments=None):
    async with Client(server) as client:
        return await client.call_tool(name, arguments or {}, raise_on_error=False)


async def test_401_echoing_the_key_is_authentication_and_leaks_nothing(server_and_settings, capsys):
    configure_logging("INFO", [KEY])  # inside the test, so stderr is the captured stream
    server, _ = server_and_settings
    result = await call(server, "call_upstream")
    assert result.is_error
    assert result.structured_content["category"] == "authentication"
    shown = json.dumps([result.structured_content, [c.text for c in result.content]])
    assert KEY not in shown and OTHER_TOKEN not in shown
    assert "Invalid API key" in result.structured_content["message"]
    assert result.content[0].text.startswith("[authentication] ")
    logged = capsys.readouterr().err
    assert "upstream GET /v1/anything -> 401" in logged  # the call was logged ...
    assert KEY not in logged and OTHER_TOKEN not in logged  # ... without the key


async def test_wire_shape_over_legacy_http_era(server_and_settings, capsys):
    """A raw 2025-06-18 client reads category from structuredContent, _meta and the text."""
    configure_logging("INFO", [KEY])  # inside the test, so stderr is the captured stream
    server, settings = server_and_settings
    settings.port = free_port()
    async with serving(server, settings):
        async with httpx2.AsyncClient() as client:
            url = f"http://127.0.0.1:{settings.port}/mcp"
            await rpc(client, url, "initialize", INITIALIZE)
            reply = await rpc(client, url, "tools/call", {"name": "call_upstream", "arguments": {}})
            health = await client.get(f"http://127.0.0.1:{settings.port}/health")
    result = reply["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["category"] == "authentication"
    assert result["_meta"]["category"] == "authentication"
    assert result["content"][0]["text"].startswith("[authentication] ")
    for text in (json.dumps(reply), health.text, capsys.readouterr().err):
        assert KEY not in text and OTHER_TOKEN not in text


async def test_unexpected_exception_is_generic_and_detail_goes_to_redacted_stderr(
    server_and_settings, capsys
):
    configure_logging("INFO", [KEY])  # inside the test, so stderr is the captured stream
    server, _ = server_and_settings
    result = await call(server, "explode")
    assert result.is_error
    assert result.structured_content == {"category": "internal_error", "message": GENERIC_MESSAGE}
    shown = json.dumps([result.structured_content, [c.text for c in result.content]])
    assert "RuntimeError" not in shown and "password" not in shown and "/secret/path" not in shown
    logged = capsys.readouterr().err
    assert "RuntimeError" in logged and "password=" in logged  # full detail is logged ...
    assert KEY not in logged and OTHER_TOKEN not in logged  # ... with secrets redacted
    assert logging.getLogger("fastmcp").handlers == []  # FastMCP's own Rich handler stays off


async def test_hand_written_tool_error_is_not_trusted_text(server_and_settings, capsys):
    configure_logging("INFO", [KEY])  # inside the test, so stderr is the captured stream
    server, _ = server_and_settings
    result = await call(server, "plain_tool_error")
    assert result.structured_content == {"category": "internal_error", "message": GENERIC_MESSAGE}
    assert "hand-written" not in json.dumps(result.structured_content)
    assert KEY not in capsys.readouterr().err


async def test_database_lock_is_storage_busy(server_and_settings):
    server, _ = server_and_settings
    result = await call(server, "database_locked")
    assert result.structured_content["category"] == "storage_busy"
    assert "busy" in result.structured_content["message"]


async def test_bad_arguments_and_unknown_tools_are_categorized(server_and_settings):
    server, _ = server_and_settings
    bad = await call(server, "needs_int", {"n": "abc"})
    assert bad.structured_content["category"] == "invalid_request"
    missing = await call(server, "no_such_tool")
    assert missing.structured_content["category"] == "not_found"


def test_the_vocabulary_is_exactly_the_eleven_spec_values():
    assert set(ALL_CATEGORIES) == SPEC_VOCABULARY and len(ALL_CATEGORIES) == 11


@pytest.mark.parametrize("category", sorted(SPEC_VOCABULARY))
async def test_every_category_round_trips_and_is_sanitized(server_and_settings, category):
    server, _ = server_and_settings
    result = await call(server, "raise_category", {"category": category})
    assert result.structured_content["category"] == category
    assert KEY not in result.structured_content["message"]


async def test_every_failure_kind_lands_in_the_closed_vocabulary(server_and_settings):
    server, _ = server_and_settings
    calls = [
        ("call_upstream", {}),
        ("explode", {}),
        ("plain_tool_error", {}),
        ("database_locked", {}),
        ("needs_int", {"n": "x"}),
        ("no_such_tool", {}),
        ("raise_category", {"category": "internal_error"}),
    ]
    for name, arguments in calls:
        result = await call(server, name, arguments)
        assert result.is_error, name
        assert result.structured_content["category"] in SPEC_VOCABULARY, name

"""agent-help task 4.1: the size budget of the ``tools/list`` response (help-tool spec)."""

import httpx2
import pytest
from server_support import HEADERS, free_port, serving

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

# Measured 2026-10-13 on the live server after the routing modes (acceptance record of
# routing-modes-config): 59779 bytes for ten tools. With the help tool (eleven) the live server
# measured 55512 (agent-help acceptance); the cap stays at the spec's number.
BUDGET = 59779


@pytest.fixture
async def make_server(make_settings):
    built = []

    async def factory(**overrides):
        settings = make_settings(**overrides)
        migrate(settings)
        engine = create_engine_for(settings)
        http = httpx2.AsyncClient()
        built.append((http, engine))
        return build_server(settings, http, engine), settings

    yield factory
    for http, engine in built:
        await http.aclose()
        await engine.dispose()


async def test_the_tools_list_response_stays_within_its_budget(make_server):
    server, settings = await make_server(port=free_port())
    async with serving(server, settings):
        async with httpx2.AsyncClient() as client:
            response = await client.post(
                f"http://127.0.0.1:{settings.port}/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                headers=HEADERS,
            )
    size = len(response.content)
    names = [t["name"] for t in response.json()["result"]["tools"]]
    assert "perplexity_help" in names and len(names) == 11
    assert size <= BUDGET, f"tools/list is {size} bytes, budget {BUDGET}"

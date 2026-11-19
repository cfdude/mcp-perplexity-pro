"""agent-help task 4.1: the size budget of the ``tools/list`` response (help-tool spec)."""

import httpx2
import pytest
from server_support import HEADERS, free_port, serving

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

# Measured 2026-10-13 on the live server after the routing modes (acceptance record of
# routing-modes-config): 59779 bytes for ten tools. With the help tool (eleven) the live server
# measured 55512 (agent-help acceptance); the cap stays at the spec's number. Test-server sizes
# after routing-rules-v1 and routing-decisions-classifier: default 56545, dynamic 56831,
# dynamic with the Decisions classifier 57065 (measured 2026-10-15). After model-matrix task 5.1
# (the ``efforts`` and ``matrix`` output fields of perplexity_models, +1022 bytes each): default
# 57567, dynamic 57853, dynamic with the Decisions classifier 58087 (measured 2026-10-18).
# api-drift-2026-10 task 3.1 (the decider model text, eight names, and the flash price): default
# 57735, dynamic 58021, dynamic with the Decisions classifier 58255 (measured 2026-10-29, +168).
# media-inputs task 3.3 (measured 2026-11-19, the three test servers): `attachments` on ask (+203)
# and chat (+209), the `inputs` string of perplexity_models (+85) and the six-topic sentence of
# perplexity_help (+13) grew each variant by 510 bytes over the commit the change started from
# (default 57735, dynamic 58021, dynamic with Decisions 58255). The cap stays 59779; the ceilings
# below are this change's own and are only for catching later growth. A change that adds more
# raises them in its own task, never past BUDGET.
BUDGET = 59779
BASE = {"default": 57735, "dynamic": 58021, "dynamic-decisions": 58255}
CEILING = {"default": 58250, "dynamic": 58550, "dynamic-decisions": 58800}
GROWTH_CAP = 900  # the gross growth media-inputs may add over BASE (design D14)
# sha256 (first 16 hex) of each tool as listed, compact JSON with sorted keys, at the starting
# commit: perplexity_search and perplexity_decide are not touched by media-inputs
UNTOUCHED = {"perplexity_decide": "a3a6370d4b8378c4", "perplexity_search": "1e4aab4731f90f3e"}


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


async def tools_list(make_server, **overrides) -> tuple[int, list[dict]]:
    server, settings = await make_server(port=free_port(), **overrides)
    async with serving(server, settings):
        async with httpx2.AsyncClient() as client:
            response = await client.post(
                f"http://127.0.0.1:{settings.port}/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                headers=HEADERS,
            )
    return len(response.content), response.json()["result"]["tools"]


async def tools_list_size(make_server, **overrides) -> tuple[int, list[str]]:
    size, tools = await tools_list(make_server, **overrides)
    return size, [t["name"] for t in tools]


@pytest.mark.parametrize(
    "overrides",
    [{}, {"routing": "dynamic"}, {"routing": "dynamic", "classifier": "decisions"}],
    ids=["default", "dynamic", "dynamic-decisions"],
)
async def test_the_tools_list_response_stays_within_its_budget(make_server, overrides):
    size, names = await tools_list_size(make_server, **overrides)
    assert "perplexity_help" in names and len(names) == 11
    assert size <= BUDGET, f"tools/list is {size} bytes, budget {BUDGET}"


VARIANTS = [
    ("default", {}),
    ("dynamic", {"routing": "dynamic"}),
    ("dynamic-decisions", {"routing": "dynamic", "classifier": "decisions"}),
]


@pytest.mark.parametrize(("variant", "overrides"), VARIANTS, ids=[v[0] for v in VARIANTS])
async def test_each_variant_stays_under_this_changes_ceiling_and_its_growth_cap(
    make_server, variant, overrides
):
    size, _ = await tools_list_size(make_server, **overrides)
    assert size <= CEILING[variant] <= BUDGET, (
        f"{variant}: {size} bytes, ceiling {CEILING[variant]}"
    )
    assert size - BASE[variant] <= GROWTH_CAP, f"{variant}: grew {size - BASE[variant]} bytes"


@pytest.mark.parametrize(("variant", "overrides"), VARIANTS, ids=[v[0] for v in VARIANTS])
async def test_search_and_decide_are_byte_identical_to_the_starting_commit(
    make_server, variant, overrides
):
    import hashlib
    import json

    _, tools = await tools_list(make_server, **overrides)
    got = {
        t["name"]: hashlib.sha256(
            json.dumps(t, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()[:16]
        for t in tools
        if t["name"] in UNTOUCHED
    }
    assert got == UNTOUCHED


async def test_research_has_no_attachments_parameter_and_the_flag_tools_do(make_server):
    _, tools = await tools_list(make_server)
    by_name = {t["name"]: t for t in tools}
    assert "attachments" not in by_name["perplexity_research"]["inputSchema"]["properties"]
    for name in ("perplexity_ask", "perplexity_chat"):
        assert "attachments" in by_name[name]["inputSchema"]["properties"]

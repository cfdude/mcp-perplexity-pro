"""Gate 2 fix-ups: identity strings (model ids, project names) survive redaction while real
keys, partial echoes and key fragments at a truncation cut do not."""

import httpx2
import pytest
from fastmcp import Client
from sqlalchemy import text

from mcp_perplexity_pro import usage as usage_module
from mcp_perplexity_pro.pricing import DECISIONS_NANO_PER_INPUT_TOKEN, EMBEDDINGS_NANO_PER_TOKEN
from mcp_perplexity_pro.redaction import redact_text
from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.projects import PerplexityError, validate_project_name
from mcp_perplexity_pro.usage import MAX_TEXT, record_usage

MODELS = [*EMBEDDINGS_NANO_PER_TOKEN, *DECISIONS_NANO_PER_INPUT_TOKEN]
KEY = "pplx-" + "Zy9_" * 12  # 48 key characters
ALNUM_KEY = "pplx-" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5hI7jK9lM1nO3"


async def rows(engine, sql="SELECT * FROM usage_events ORDER BY id"):
    async with engine.connect() as conn:
        return [dict(r._mapping) for r in await conn.execute(text(sql))]


def test_the_model_list_covers_every_priced_model():
    assert len(MODELS) == 6 and all(m.startswith("pplx-") for m in MODELS)


@pytest.mark.parametrize("model", MODELS)
def test_a_documented_model_id_survives_redaction(model):
    assert redact_text(model) == model
    assert redact_text(f"model {model}, ok") == f"model {model}, ok"


@pytest.mark.parametrize("model", MODELS)
async def test_a_documented_model_id_is_stored_unchanged(storage_engine, model):
    assert await record_usage(storage_engine, tool="t", api="embeddings", model=model)
    assert [r["model"] for r in await rows(storage_engine)] == [model]


@pytest.mark.parametrize(
    "shaped",
    [
        KEY,
        ALNUM_KEY,
        "pplx-embed-" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5hI7j",  # a key dressed as a model
        "pplx-" + "aB3dE5gH",  # a partial echo
    ],
)
def test_key_shaped_strings_are_still_redacted(shaped):
    assert "aB3" not in redact_text(shaped) and "Zy9" not in redact_text(shaped)
    assert redact_text(f"x {shaped} y") == "x [redacted] y"


# --- project names ----------------------------------------------------------------------------

NAMES = [
    "pplx-embeddings",
    "pplx-short",
    "pplx-decider-v1.1-27b",
    "pplx-" + "a" * 19,  # one short of the validator's key shape
    "a",
    "My_project.v2",
]


@pytest.mark.parametrize("name", NAMES)
async def test_every_accepted_project_name_survives_the_recorder_unchanged(storage_engine, name):
    assert validate_project_name(name) == name
    assert await record_usage(storage_engine, tool="t", api="agent", project=name)
    (row,) = await rows(storage_engine)
    assert row["project_name"] == name


async def test_a_name_the_validator_refuses_is_stored_as_null_and_never_raises(
    storage_engine, caplog
):
    for bad in (KEY, "has space", "../x", ".hidden", "x" * 65):
        with pytest.raises(PerplexityError):
            validate_project_name(bad)
        assert await record_usage(storage_engine, tool="t", api="agent", project=bad) is True
    stored = await rows(storage_engine)
    assert [(r["project_name"], r["project_id"]) for r in stored] == [(None, None)] * 5
    assert "Zy9_Zy9_" not in caplog.text


async def test_perplexity_usage_finds_the_spend_of_a_project_named_pplx_embeddings(
    make_settings, storage_engine
):
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: None))
    server = build_server(make_settings(), http, storage_engine)
    async with storage_engine.begin() as conn:
        await conn.execute(text("INSERT INTO projects (name) VALUES ('pplx-embeddings')"))
    await record_usage(
        storage_engine, tool="t", api="agent", project="pplx-embeddings", usage=usage_module.Usage()
    )
    async with Client(server) as client:
        result = await client.call_tool(
            "perplexity_usage", {"project": "pplx-embeddings"}, raise_on_error=False
        )
    await http.aclose()
    assert not result.is_error and result.structured_content["totals"]["calls"] == 1
    (row,) = await rows(storage_engine)
    assert row["project_id"] is not None


# --- truncation happens after redaction ------------------------------------------------------


async def test_a_key_straddling_the_identity_cut_leaves_no_fragment(storage_engine):
    filler = "x" * (MAX_TEXT - 8)
    straddling = filler + " " + KEY  # the cut falls inside the key
    await record_usage(
        storage_engine, tool="t", api="agent", model=straddling, request_id=straddling
    )
    (row,) = await rows(storage_engine)
    for column in ("model", "request_id"):
        assert "pplx" not in row[column] and "Zy" not in row[column]


def test_a_key_straddling_the_repr_cut_leaves_no_fragment():
    value = "y" * 70 + KEY
    shown = usage_module._safe(value, ())
    assert "pplx" not in shown and "Zy9" not in shown


# --- upstream key names in log lines -----------------------------------------------------------


def test_an_upstream_tool_key_name_reaches_the_log_capped_and_on_one_line(caplog):
    from mcp_perplexity_pro.usage import usage_from_agent_response

    hostile = "evil\nFORGED LOG LINE " + "z" * 300 + KEY
    usage = {"tool_calls_details": {hostile: "not a mapping"}}
    with caplog.at_level("WARNING"):
        usage_from_agent_response(usage)
    (record,) = caplog.records
    message = record.getMessage()
    assert "\n" not in message and "Zy9" not in message and "pplx" not in message
    assert len(message) < 200

"""Tasks 7.1 and 7.2 (py-embeddings): ``perplexity_embed`` through ``build_server``."""

import base64
import json

import jsonschema
import pytest
from agent_support import make_world
from embeddings_support import REAL, embed_response
from fastmcp import Client

TOOL = "perplexity_embed"
DIMS = 128


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder=None):
        w = await make_world(
            make_settings, responder or (lambda request, n: embed_response(request))
        )
        made.append(w)
        return w

    yield build
    for w in made:
        await w.aclose()


def category(result):
    assert result.is_error
    return result.structured_content["category"]


async def nothing_happened(w):
    assert w.requests == []
    assert await w.count("usage_events") == 0
    assert await w.count("projects") == 0


def two_texts():
    return [{"key": "alpha", "text": "first text"}, {"key": "beta", "text": "second text"}]


async def index_texts(w, **kwargs):
    return await w.call(
        TOOL, action="index", source="text", items=two_texts(), dimensions=DIMS, **kwargs
    )


def has_vector(result) -> bool:
    blob = json.dumps(result.structured_content) + " ".join(c.text for c in result.content)
    return any(base64.b64encode(v).decode() in blob for v in REAL[:4])


async def test_listing_has_schema_annotations_privacy_prices_and_described_parameters(world):
    w = await world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    assert tool.output_schema and "hits" in tool.output_schema["properties"]
    ann = tool.annotations
    assert (ann.read_only_hint, ann.destructive_hint, ann.open_world_hint) == (False, True, True)
    desc = " ".join(tool.description.split())
    assert "SENDS the text" in desc and "never returned" in desc
    assert "$0.004" in desc and "$0.03" in desc and "remaining" in desc
    props = tool.input_schema["properties"]
    assert all(p.get("description") for p in props.values())
    assert {"action", "source", "items", "query", "top_k", "limit", "project", "confirm"} <= set(
        props
    )


async def test_index_then_search_returns_the_matching_chunk_and_validates_against_the_schema(world):
    w = await world()
    async with Client(w.server) as client:
        schema = next(t for t in await client.list_tools() if t.name == TOOL).output_schema
    indexed = await index_texts(w)
    assert not indexed.is_error
    jsonschema.validate(indexed.structured_content, schema)
    sc = indexed.structured_content
    assert (sc["embedded_chunks"], sc["embedded_items"], sc["requests"], sc["remaining"]) == (
        2,
        2,
        1,
        0,
    )
    assert sc["cost_source"] == "reported" and sc["cost_usd"] == "0.00000008"
    # the search query embeds to REAL[0], the vector the first indexed text was stored with
    found = await w.call(TOOL, action="search", query="first", dimensions=DIMS, top_k=2)
    jsonschema.validate(found.structured_content, schema)
    hits = found.structured_content["hits"]
    assert hits[0]["key"] == "alpha" and hits[0]["score"] == pytest.approx(1.0, abs=1e-5)
    assert [h["key"] for h in hits] == ["alpha", "beta"] and hits[0]["text"] == "first text"
    assert "1. [1.0000]" in found.content[0].text
    assert not has_vector(indexed) and not has_vector(found)


async def test_a_repeat_index_makes_no_request_and_reports_no_cost(world):
    w = await world()
    await index_texts(w)
    again = await index_texts(w)
    sc = again.structured_content
    assert (sc["requests"], sc["skipped_items"], sc["cost_usd"], sc["cost_source"]) == (
        0,
        2,
        None,
        None,
    )


async def test_confirm_must_be_the_boolean_true_not_a_truthy_string(world):
    w = await world()
    await index_texts(w)
    for loose in ("yes", "true", 1):
        refused = await w.call(TOOL, action="delete", confirm=loose)
        assert refused.is_error and await w.count("embedding_chunks") == 2
    assert (await w.call(TOOL, action="delete", confirm=True)).structured_content["removed"] == 2


async def test_status_counts_what_is_stored_and_what_is_not_without_any_request(world):
    w = await world()
    await index_texts(w)
    before = len(w.requests)
    status = await w.call(TOOL, action="status", dimensions=DIMS)
    sc = status.structured_content
    assert sc["groups"] == [
        {
            "source": "text",
            "model": "pplx-embed-v1-0.6b",
            "dimensions": DIMS,
            "encoding": "int8",
            "chunks": 2,
        }
    ]
    assert (sc["unindexed_chat"], sc["unindexed_job"]) == (0, 0)
    assert len(w.requests) == before and await w.count("usage_events") == 1


async def test_delete_needs_confirm_and_then_removes_the_matching_chunks(world):
    w = await world()
    await index_texts(w)
    refused = await w.call(TOOL, action="delete", source="text")
    assert category(refused) == "confirmation_required"
    assert await w.count("embedding_chunks") == 2
    done = await w.call(TOOL, action="delete", source="text", confirm=True)
    assert done.structured_content["removed"] == 2 and await w.count("embedding_chunks") == 0


async def test_an_unknown_action_and_every_local_refusal_fail_with_nothing_sent_or_stored(world):
    w = await world()
    refusals = [
        dict(action="rebuild"),
        dict(action="index"),  # no source
        dict(action="index", source="text"),  # no items
        dict(action="index", source="text", items=[{"key": "a", "text": " "}]),
        dict(action="index", source="chat", items=two_texts()),
        dict(action="index", source="text", items=two_texts(), limit=0),
        dict(action="index", source="text", items=two_texts(), dimensions=130),
        dict(action="index", source="text", items=two_texts(), model="nope"),
        dict(action="index", source="text", items=two_texts(), encoding="float"),
        dict(action="search"),
        dict(action="search", query=" "),
        dict(action="search", query="q", top_k=21),
        dict(action="search", query="q", min_score=2),
        dict(action="search", query="q", source="chats"),
        dict(action="delete", confirm=True, source="nope"),
        dict(action="status", dimensions=130),
    ]
    for kwargs in refusals:
        result = await w.call(TOOL, **kwargs)
        assert category(result) == "invalid_request", kwargs
    await nothing_happened(w)


async def test_status_delete_and_a_search_of_nothing_create_no_project_and_make_no_request(world):
    w = await world()
    assert not (await w.call(TOOL, action="status")).is_error
    assert (await w.call(TOOL, action="delete", confirm=True)).structured_content["removed"] == 0
    empty = await w.call(TOOL, action="search", query="anything")
    assert empty.structured_content["hits"] == [] and empty.structured_content["warnings"]
    await nothing_happened(w)


async def test_a_named_project_is_used_and_an_invalid_one_does_nothing(world):
    w = await world()
    named = await index_texts(w, project="alpha")
    assert named.structured_content["project"] == "alpha"
    assert (await w.rows("SELECT project_name FROM usage_events")) == [("alpha",)]
    w2 = await world()
    bad = await w2.call(TOOL, action="index", source="text", items=two_texts(), project="../x")
    assert category(bad) == "invalid_request"
    assert await w2.count("projects") == 1  # w2 shares the data directory with w: only 'alpha'

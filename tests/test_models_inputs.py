"""Task 2.4: ``perplexity_models`` shows each model's inputs as one short string (model-catalog)."""

import json
from datetime import UTC, datetime

import pytest
from fastmcp import Client
from matrix_support import MatrixWorld, Upstream, make_matrix_world, payload_with

from mcp_perplexity_pro import matrix
from mcp_perplexity_pro.tools.models import ListedModel, inputs_string

NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)
BASE_BYTES = 14757  # structured content for the 54 swept models before inputs existed


@pytest.fixture
async def make_world(make_settings):
    made: list[MatrixWorld] = []

    async def factory(upstream: Upstream | None = None, **kwargs) -> MatrixWorld:
        world = await make_matrix_world(
            make_settings, upstream or Upstream(), refresh_task=False, **kwargs
        )
        made.append(world)
        return world

    yield factory
    for world in made:
        await world.aclose()


async def models(world: MatrixWorld, **arguments):
    async with Client(world.server) as client:
        result = await client.call_tool("perplexity_models", arguments, raise_on_error=False)
    assert not result.is_error, result.content
    return result


def by_id(result) -> dict:
    return {m["id"]: m for m in result.structured_content["models"]}


def test_inputs_strings_follow_the_matrix_and_are_empty_when_unknown():
    base = matrix.load_baseline()
    assert inputs_string("openai/gpt-6-luna", base) == "image,document"
    assert inputs_string("xai/grok-4.3", base) == "(refused document)"
    assert inputs_string("acme/not-in-the-matrix", base) == ""


def test_a_model_that_accepts_images_and_refuses_documents_reads_both():
    base = matrix.load_baseline().model_copy(deep=True)
    entry = base.models["openai/gpt-6-luna"]
    entry.inputs.accepted = ["image"]
    entry.inputs.refused = {"document": 400}
    entry.inputs.attempts = {"image": 1, "document": 1}  # attempted: the baseline is not consulted
    assert inputs_string("openai/gpt-6-luna", base) == "image (refused document)"


def test_a_removed_model_has_no_inputs_string():
    base = matrix.load_baseline().model_copy(deep=True)
    base.models["openai/gpt-6-luna"].status = "removed"
    assert inputs_string("openai/gpt-6-luna", base) == ""


async def test_the_result_carries_the_string_and_a_model_the_matrix_lacks_gets_empty(make_world):
    world = await make_world(Upstream(models=payload_with("acme/live-only")))
    rows = by_id(await models(world))
    assert rows["openai/gpt-6-luna"]["inputs"] == "image,document"
    assert rows["xai/grok-4.3"]["inputs"] == "(refused document)"
    assert rows["acme/live-only"]["inputs"] == ""


async def test_the_text_table_shows_the_column_and_says_what_empty_and_audio_mean(make_world):
    world = await make_world(Upstream(models=payload_with("acme/live-only")))
    text = (await models(world)).content[0].text
    header = next(line for line in text.splitlines() if line.startswith("id | provider"))
    assert header.endswith("| inputs")
    luna = next(line for line in text.splitlines() if line.startswith("openai/gpt-6-luna |"))
    assert luna.endswith("| image,document")
    live = next(line for line in text.splitlines() if line.startswith("acme/live-only |"))
    assert live.endswith("| -")
    assert "audio and video are not accepted by the API" in text
    assert "unknown, not unsupported" in text
    assert " models have an input kind unknown" in text  # the count lives in the text only


def test_the_schema_adds_one_short_string_and_no_object_or_matrix_count():
    props = ListedModel.model_json_schema()["properties"]
    assert props["inputs"]["type"] == "string"
    assert len(props["inputs"]["description"]) <= 30
    from mcp_perplexity_pro.tools.models import MatrixSection

    assert set(MatrixSection.model_json_schema()["properties"]) == {
        "origin",
        "fetched_at",
        "unprobed",
    }


async def test_the_inputs_field_adds_at_most_1700_bytes_of_structured_content_and_1800_of_text(
    make_world,
):
    got = await models(await make_world())
    rows = got.structured_content["models"]
    plain = [{k: v for k, v in m.items() if k != "inputs"} for m in rows]
    grown = len(json.dumps(rows, separators=(",", ":"))) - len(
        json.dumps(plain, separators=(",", ":"))
    )
    assert 0 < grown <= 1700
    text = got.content[0].text
    table = [line for line in text.splitlines() if line.count(" | ") == 8]
    column = sum(len(line.rsplit(" | ", 1)[1]) + 3 for line in table)
    assert 0 < column <= 1800

"""model-matrix task 5.1: ``perplexity_models`` reports each model's efforts and the matrix.

The matrix is the stored file (or the packaged baseline); the tool joins it to the live list by
model id and never refreshes it (``refresh`` on the tool refreshes only the catalog list).
"""

from datetime import UTC, datetime

import pytest
from fastmcp import Client
from matrix_support import MatrixWorld, Upstream, make_matrix_world, payload_with

from mcp_perplexity_pro import help_text, matrix

NOW = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)
LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"]
NANO = "openai/gpt-5-nano"


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


async def store(world: MatrixWorld, change=None) -> None:
    """Write the baseline (changed by ``change``) as the stored file."""

    def apply(current: matrix.Matrix) -> matrix.Matrix:
        copy = current.model_copy(deep=True)
        if change is not None:
            change(copy)
        return copy

    result = await matrix.update(world.settings.data_dir, apply, now=NOW)
    assert result.status == "written"


def add_row(m: matrix.Matrix, model_id: str, **fields) -> None:
    values = {
        "provider": "acme",
        "status": "available",
        "first_seen": "2026-10-18T00:00:00Z",
        "last_seen": "2026-10-18T00:00:00Z",
        **fields,
    }
    m.models[model_id] = matrix.ModelEntry(**values)


# --- the model-catalog delta --------------------------------------------------------------------


async def test_a_model_lists_its_accepted_and_refused_levels_and_their_source(make_world):
    world = await make_world()
    entry = by_id(await models(world))[NANO]
    assert entry["efforts"] == {
        "accepted": ["minimal", "low", "medium", "high"],
        "refused": ["xhigh", "max"],
        "source": "baseline",
    }
    full = by_id(await models(world))["anthropic/claude-fable-5"]["efforts"]
    assert full["accepted"] == LEVELS and full["refused"] == []


async def test_the_result_carries_a_matrix_object_with_origin_fetched_at_and_unprobed(make_world):
    world = await make_world()
    section = (await models(world)).structured_content["matrix"]
    baseline = matrix.load_baseline()
    assert section == {"origin": "baseline", "fetched_at": baseline.fetched_at, "unprobed": 0}


async def test_a_stored_file_is_the_origin_file_and_is_what_the_efforts_come_from(make_world):
    world = await make_world()

    def change(m):
        m.models[NANO].efforts.accepted = ["low"]
        m.models[NANO].efforts.refused = {lv: 400 for lv in LEVELS if lv != "low"}
        m.fetched_at = "2026-10-18T12:00:00Z"

    await store(world, change)
    result = await models(world)
    assert result.structured_content["matrix"]["origin"] == "file"
    assert result.structured_content["matrix"]["fetched_at"] == "2026-10-18T12:00:00Z"
    assert by_id(result)[NANO]["efforts"]["accepted"] == ["low"]


async def test_a_model_the_matrix_lacks_is_listed_without_efforts_and_the_count_is_unchanged(
    make_world,
):
    plain = await make_world()
    before = (await models(plain)).structured_content["matrix"]["unprobed"]
    world = await make_world(Upstream(models=payload_with("acme/live-only")))
    result = await models(world)
    entry = by_id(result)["acme/live-only"]
    assert "efforts" not in entry  # listed, with no efforts key at all
    assert entry["pricing"]["input"] == 1.0
    assert result.structured_content["matrix"]["unprobed"] == before == 0


async def test_unprobed_counts_available_matrix_rows_not_listed_ids_and_not_removed_rows(
    make_world,
):
    world = await make_world(Upstream(models=payload_with("acme/new-a", "acme/new-b")))

    def change(m):
        add_row(m, "acme/new-a")  # available, unprobed, and listed
        add_row(m, "acme/stored-only")  # available, unprobed, NOT in the live list
        add_row(m, "acme/gone", status="removed")  # removed and unprobed: never counted

    await store(world, change)
    result = await models(world)
    assert result.structured_content["matrix"]["unprobed"] == 2
    ids = by_id(result)
    assert "acme/gone" not in ids and "acme/stored-only" not in ids  # the live list is the list
    assert ids["acme/new-a"]["efforts"] == {"accepted": [], "refused": [], "source": "unprobed"}
    assert "efforts" not in ids["acme/new-b"]  # in the live list, in no matrix row yet


async def test_a_listed_model_whose_row_is_removed_has_no_efforts(make_world):
    world = await make_world()
    await store(world, lambda m: setattr(m.models[NANO], "status", "removed"))
    result = await models(world)
    assert "efforts" not in by_id(result)[NANO]  # history, not a fact about a live model
    assert result.structured_content["matrix"]["unprobed"] == 0


async def test_refresh_on_the_tool_refreshes_the_catalog_and_never_the_matrix(make_world):
    world = await make_world()
    first = world.app.matrix.snapshot()
    await models(world, refresh=True)
    await models(world, refresh=True)
    assert world.upstream.count("/v1/models") == 2  # the catalog list, live each time
    assert world.app.matrix.snapshot() is first  # the matrix in memory is untouched
    assert not (world.settings.data_dir / matrix.FILENAME).exists()  # and nothing was written
    assert not (world.settings.data_dir / matrix.LOCK_FILENAME).exists()


async def test_a_corrupt_file_reads_as_the_baseline_without_touching_the_file(make_world):
    world = await make_world()
    path = world.settings.data_dir / matrix.FILENAME
    path.write_text("not json")
    result = await models(world)
    assert result.structured_content["matrix"]["origin"] == "baseline"
    assert path.read_text() == "not json"  # renamed aside only by the next write


# --- the text rendering -------------------------------------------------------------------------


async def test_the_text_shows_each_models_efforts_and_the_matrix_line(make_world):
    world = await make_world(Upstream(models=payload_with("acme/live-only")))
    text = (await models(world)).content[0].text
    assert "efforts" in text.splitlines()[1] or "efforts" in text.splitlines()[2]
    nano = next(line for line in text.splitlines() if line.startswith(f"{NANO} |"))
    assert "minimal,low,medium,high" in nano and "refused xhigh,max" in nano
    fable = next(line for line in text.splitlines() if line.startswith("anthropic/claude-fable-5"))
    assert fable.rstrip().endswith("all")
    live_only = next(line for line in text.splitlines() if line.startswith("acme/live-only"))
    assert live_only.rstrip().endswith("-")
    assert "Matrix: baseline" in text and "0 unprobed" in text


# --- the help ------------------------------------------------------------------------------------


def test_the_help_entry_describes_efforts_and_the_matrix(make_settings):
    entry = help_text.TOOLS["perplexity_models"]
    assert "matrix" in entry["result"]["always"]
    text = help_text.render_tool("perplexity_models", make_settings(), [], {"readOnlyHint": True})
    for word in ("efforts", "accepted", "refused", "unprobed", "baseline", "probe"):
        assert word in text, word
    assert "not" in text and "effective" in text  # accepted is not the same as effective


async def test_a_full_result_for_the_whole_list_stays_small(make_world):
    """Measured 2026-10-18: 14757 bytes of structured content for 54 models (acceptance README)."""
    import json

    result = await models(await make_world())
    assert len(by_id(result)) == 54
    assert len(json.dumps(result.structured_content, separators=(",", ":"))) < 16000

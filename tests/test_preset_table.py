"""api-drift-2026-10 task 2.1: the documented preset table (spec ``model-catalog``, "The preset
table follows the documentation"). The table is copied by hand from Perplexity's documentation
(https://docs.perplexity.ai/docs/agent-api/presets.md, read 2026-10-29); nothing else pinned it."""

from mcp_perplexity_pro.catalog import PRESETS

DOCUMENTED = {
    "fast": "openai/gpt-6-luna",
    "low": "openai/gpt-6-luna",
    "medium": "openai/gpt-6-luna",
    "high": "openai/gpt-6.1-terra",
    "xhigh": "anthropic/claude-opus-5-5",
}


def test_the_table_is_the_documentation_of_2026_10_29():
    assert PRESETS.as_of == "2026-10-29" and PRESETS.source == "documentation"
    assert {p.name: p.model for p in PRESETS.presets} == DOCUMENTED
    assert [p.name for p in PRESETS.presets] == list(DOCUMENTED)  # the documented order


def test_the_note_says_documentation_and_that_perplexity_manages_versioned_presets():
    note = PRESETS.note
    assert "documentation" in note and "not from the live API" in note
    assert "fast@2026-10-16.0" in note
    assert "unversioned" not in note  # presets carry versions now


async def test_the_tool_result_carries_the_table(make_settings):
    from agent_support import make_world, respond_with

    w = await make_world(make_settings, respond_with("models.json"))
    try:
        result = await w.call("perplexity_models")
    finally:
        await w.aclose()
    section = result.structured_content["presets"]
    assert section["as_of"] == "2026-10-29"
    assert {p["name"]: p["model"] for p in section["presets"]}["high"] == "openai/gpt-6.1-terra"

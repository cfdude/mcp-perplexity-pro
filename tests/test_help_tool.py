"""agent-help task 2.1: ``perplexity_help`` through ``build_server`` (help-tool spec)."""

import pytest
from agent_support import make_world, respond_with
from fastmcp import Client

TOOL = "perplexity_help"
CUSTOM = {
    "routing": "custom",
    "tier_light": "x/light",
    "tier_standard": "x/standard",
    "tier_complex": "x/complex",
}


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(**settings):
        w = await make_world(make_settings, respond_with("agent_fast.json"), **settings)
        made.append(w)
        return w

    yield build
    for w in made:
        await w.aclose()


async def test_the_listing_has_schema_and_read_only_annotations(world):
    w = await world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    assert tool.output_schema and set(tool.input_schema["properties"]) == {"action", "name"}
    a = tool.annotations
    assert (a.read_only_hint, a.destructive_hint, a.open_world_hint) == (True, False, False)


async def test_the_index_is_the_default_action(world):
    w = await world()
    out = (await w.call(TOOL)).structured_content
    assert out["action"] == "index" and out["text"].startswith("# perplexity-pro")
    assert "perplexity_help" in out["tools"] and out["topics"] == [
        "routing",
        "costs",
        "citations",
        "errors",
        "projects",
    ]
    assert len(out["text"].encode()) <= 1500 and out["text"].isascii()
    assert "perplexity_help" in out["text"]  # every registered tool, itself included


async def test_the_text_content_is_the_markdown(world):
    w = await world()
    result = await w.call(TOOL, action="topic", name="costs")
    assert result.content[0].text == result.structured_content["text"]


async def test_tool_help_reads_the_live_schema(world):
    w = await world()
    out = (await w.call(TOOL, action="tool", name="perplexity_ask")).structured_content
    text = out["text"]
    assert out["name"] == "perplexity_ask" and "## Arguments" in text
    for argument in ("query", "depth", "tier", "model", "search", "json_schema"):
        assert f"- {argument} (" in text
    assert "string or null" in text and "billed" in text


async def test_every_tool_has_a_page_and_the_help_tool_documents_itself(world):
    w = await world()
    names = (await w.call(TOOL)).structured_content["tools"]
    for name in names:
        result = await w.call(TOOL, action="tool", name=name)
        assert not result.is_error and result.structured_content["text"].startswith(f"# {name}")
    help_page = (await w.call(TOOL, action="tool", name=TOOL)).structured_content["text"]
    assert "free, read-only" in help_page


@pytest.mark.parametrize(
    "arguments, mention",
    [
        ({"action": "tool", "name": "perplexity_ask2"}, "perplexity_ask"),
        ({"action": "tool"}, "perplexity_search"),
        ({"action": "topic", "name": "pricing"}, "costs"),
        ({"action": "topic"}, "routing"),
        ({"action": "explain"}, "index"),
    ],
)
async def test_bad_calls_are_invalid_request_naming_the_valid_values(world, arguments, mention):
    w = await world()
    result = await w.call(TOOL, **arguments)
    assert result.is_error and result.structured_content["category"] == "invalid_request"
    assert mention in result.structured_content["message"]


async def test_the_routing_topic_follows_the_server_mode(world):
    standard = (await (await world()).call(TOOL, action="topic", name="routing")).structured_content
    assert "perplexity/sonar" in standard["text"]
    custom = (
        await (await world(**CUSTOM)).call(TOOL, action="topic", name="routing")
    ).structured_content
    assert "x/complex" in custom["text"]


async def test_help_costs_nothing_and_leaves_no_trace(world):
    w = await world()
    await w.call(TOOL)
    await w.call(TOOL, action="tool", name="perplexity_ask")
    await w.call(TOOL, action="topic", name="errors")
    assert w.bodies() == [] and await w.events() == []
    assert await w.count("projects") == 0


async def test_the_five_largest_descriptions_end_with_the_pointer(world):
    w = await world()
    async with Client(w.server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    for name in (
        "perplexity_ask",
        "perplexity_chat",
        "perplexity_research",
        "perplexity_jobs",
        "perplexity_embed",
    ):
        assert tools[name].description.rstrip().endswith("call perplexity_help."), name


async def test_titles_are_not_sent_but_a_property_named_title_stays(world):
    w = await world()
    async with Client(w.server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    ask = tools["perplexity_ask"]
    assert all("title" not in spec for spec in ask.input_schema["properties"].values())
    chat = tools["perplexity_chat"]
    assert "title" in chat.input_schema["properties"]  # the argument named title

    def property_names(node):
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                yield from node["properties"]
            for value in node.values():
                yield from property_names(value)
        elif isinstance(node, list):
            for item in node:
                yield from property_names(item)

    assert "title" in set(property_names(chat.output_schema))  # the chat's own title field
    assert all("title" not in v for v in chat.output_schema["properties"].values())


def test_strip_titles_keeps_data_inside_defaults_and_enums():
    from mcp_perplexity_pro.server import strip_titles

    schema = {
        "title": "Gone",
        "properties": {
            "title": {"title": "Title", "type": "string", "default": {"title": "kept"}},
            "kind": {"enum": [{"title": "kept"}], "title": "Kind"},
        },
    }
    assert strip_titles(schema) == {
        "properties": {
            "title": {"type": "string", "default": {"title": "kept"}},
            "kind": {"enum": [{"title": "kept"}]},
        }
    }

"""agent-help task 1.1: the pure help text (index, tool, topic) and its drift guards."""

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from fastmcp import Client

from mcp_perplexity_pro import help_text
from mcp_perplexity_pro.errors import ALL_CATEGORIES
from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()
TIERS = {"tier_light": "x/light", "tier_standard": "x/standard", "tier_complex": "x/complex"}


@pytest.fixture
async def tools(make_settings):
    """The registered tools as plain data: name -> (input schema, output schema, annotations)."""
    import httpx2

    settings = make_settings()
    migrate(settings)
    engine = create_engine_for(settings)
    http = httpx2.AsyncClient()
    async with Client(build_server(settings, http, engine)) as client:
        listed = await client.list_tools()
    data = {
        t.name: (
            t.input_schema,
            t.output_schema or {},
            t.annotations.model_dump(by_alias=True, exclude_none=True),
        )
        for t in listed
    }
    await http.aclose()
    await engine.dispose()
    return data


def uncovered(registered):
    """Registered tools that have no curated help entry."""
    return set(registered) - set(help_text.TOOLS)


def test_the_module_imports_neither_fastmcp_nor_storage():
    code = (
        "import sys\n"
        "for name in ('fastmcp', 'sqlalchemy', 'httpx2', 'mcp'):\n"
        "    sys.modules[name] = None\n"  # a blocked import raises ImportError
        "import mcp_perplexity_pro.help_text\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_every_registered_tool_has_a_curated_entry(tools):
    assert uncovered(tools) == set() and set(help_text.TOOLS) == set(tools)


def test_the_index_is_small_ascii_and_names_everything(make_settings, tools):
    text = help_text.render_index(make_settings(), sorted(tools), "2.0.0")
    assert len(text.encode("utf-8")) <= 1500, len(text.encode())
    assert text.isascii()
    listing = text.split("## Tools")[1].split("## Topics")[0]
    for name in tools:
        assert listing.count(name) == 1, name
    for topic in help_text.TOPICS:
        assert topic in text
    assert "standard" in text and "perplexity/sonar" in text


def test_the_index_states_the_custom_mode(make_settings, tools):
    text = help_text.render_index(make_settings(routing="custom", **TIERS), sorted(tools), "2.0.0")
    assert "custom" in text and len(text.encode()) <= 1500


def test_the_decision_table_maps_needs_to_tools(make_settings, tools):
    text = help_text.render_index(make_settings(), sorted(tools), "2.0.0")
    table = text.split("## Pick a tool")[1].split("## Tools")[0]
    for needle in (
        "perplexity_ask",
        "perplexity_research",
        "perplexity_jobs",
        "perplexity_search",
        "perplexity_chat",
    ):
        assert needle in table


@pytest.mark.parametrize("topic", help_text.TOPICS)
def test_each_topic_is_at_most_3000_ascii_bytes(make_settings, topic):
    text = help_text.render_topic(topic, make_settings())
    assert text.isascii() and 0 < len(text.encode()) <= 3000


def test_the_routing_topic_in_standard_and_custom(make_settings):
    standard = help_text.render_topic("routing", make_settings())
    assert "standard" in standard and "perplexity/sonar" in standard
    assert "always" in standard and "cannot be combined" in standard
    custom = help_text.render_topic("routing", make_settings(routing="custom", **TIERS))
    assert all(model in custom for model in TIERS.values()) and "custom" in custom


def test_the_errors_topic_lists_every_category(make_settings):
    text = help_text.render_topic("errors", make_settings())
    for category in ALL_CATEGORIES:
        assert f"`{category}`" in text, category
    assert set(help_text.ERROR_FIXES) == set(ALL_CATEGORIES)


def test_citations_and_projects_topics_state_their_rules(make_settings):
    citations = help_text.render_topic("citations", make_settings())
    assert "[N]" in citations and "[web:N]" in citations and "ids" in citations
    projects = help_text.render_topic("projects", make_settings())
    assert "spend history" in projects and "delete" in projects


def test_the_costs_topic_names_its_samples(make_settings):
    text = help_text.render_topic("costs", make_settings())
    assert "one sample" in text or "observations" in text or "runs" in text
    assert "differs" in text  # the default model's cost differs from the per-depth figures


def test_every_dollar_figure_in_help_is_in_the_readme(make_settings, tools):
    texts = [help_text.render_topic(t, make_settings()) for t in help_text.TOPICS]
    texts.append(help_text.render_index(make_settings(), sorted(tools), "2.0.0"))
    for name, (schema, _out, ann) in tools.items():
        texts.append(
            help_text.render_tool(name, make_settings(), help_text.describe_params(schema), ann)
        )
    figures = set(re.findall(r"\$\d+\.\d+", "\n".join(texts)))
    assert figures, "help should quote costs"
    missing = {f for f in figures if f not in README}
    assert not missing, missing


def test_every_example_validates_against_its_input_schema(tools):
    for name, entry in help_text.TOOLS.items():
        if name not in tools:
            continue
        schema = tools[name][0]
        jsonschema.validate(entry["example"], schema)


def test_every_named_result_key_is_a_top_level_output_property(tools):
    for name, entry in help_text.TOOLS.items():
        if name not in tools:
            continue
        properties = tools[name][1].get("properties", {})
        for label, keys in entry["result"].items():
            for key in keys:
                assert key in properties, (name, label, key)


def test_flags_match_the_annotations(make_settings, tools):
    read_only = [n for n, (_s, _o, a) in tools.items() if a.get("readOnlyHint")]
    destructive = [n for n, (_s, _o, a) in tools.items() if a.get("destructiveHint")]
    assert read_only and destructive, "the guards below must have something to check"
    for name, (schema, _out, ann) in tools.items():
        entry = help_text.TOOLS[name]
        if ann.get("readOnlyHint"):
            assert entry["billed"] is False
        if entry["billed"]:
            assert not ann.get("readOnlyHint")
        text = help_text.render_tool(name, make_settings(), help_text.describe_params(schema), ann)
        if ann.get("destructiveHint"):
            assert "can delete" in text, name
        if ann.get("readOnlyHint"):
            assert "free" in text and "read-only" in text, name


def test_arguments_render_unions_and_enums_in_words():
    schema = {
        "properties": {
            "query": {"type": "string", "description": "The question"},
            "depth": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "A depth"},
            "kind": {"enum": ["fast", "low", "medium"], "description": "Which"},
            "n": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["query"],
    }
    params = {p["name"]: p for p in help_text.describe_params(schema)}
    assert params["query"] == {
        "name": "query",
        "type": "string",
        "required": True,
        "description": "The question",
    }
    assert params["depth"]["type"] == "string or null" and params["depth"]["required"] is False
    assert params["kind"]["type"] == "fast, low or medium"
    assert params["n"]["type"] == "integer or null"
    assert params["tags"]["type"] == "list of string"


def test_a_new_parameter_appears_without_an_edit(make_settings, tools):
    schema = json.loads(json.dumps(tools["perplexity_ask"][0]))
    schema["properties"]["brand_new"] = {"type": "boolean", "description": "Added later"}
    text = help_text.render_tool(
        "perplexity_ask",
        make_settings(),
        help_text.describe_params(schema),
        tools["perplexity_ask"][2],
    )
    assert "brand_new" in text and "Added later" in text


def test_an_unknown_name_is_refused_with_the_valid_names(make_settings):
    with pytest.raises(help_text.HelpError) as info:
        help_text.render_topic("pricing", make_settings())
    assert "name" in str(info.value) and "costs" in str(info.value)
    with pytest.raises(help_text.HelpError) as info:
        help_text.check_tool("perplexity_ask2", list(help_text.TOOLS))
    assert "perplexity_ask" in str(info.value)


def test_a_missing_entry_is_noticed(monkeypatch, tools):
    monkeypatch.delitem(help_text.TOOLS, "perplexity_help")
    assert uncovered(tools) == {"perplexity_help"}


_ = asyncio  # the fixture above is async; pytest-asyncio runs it


def test_the_cli_style_changes_only_the_example_and_the_pointer(make_settings):
    settings = make_settings()
    names = sorted(help_text.TOOLS)
    mcp = help_text.render_index(settings, names, "2.0.0")
    cli = help_text.render_index(settings, names, "2.0.0", "cli")
    assert mcp != cli and "perplexity-pro help" in cli and "perplexity_help action" in mcp
    assert len(cli.encode()) <= 1500
    assert mcp.splitlines()[:-1] == cli.splitlines()[:-1]
    params = [{"name": "query", "type": "string", "required": True, "description": "q"}]
    page = help_text.render_tool(
        "perplexity_ask", settings, params, {}, example="perplexity-pro ask 'q'"
    )
    assert "perplexity-pro ask 'q'" in page and '{"name"' not in page
    assert help_text.render_topic("costs", settings) == help_text.render_topic("costs", settings)

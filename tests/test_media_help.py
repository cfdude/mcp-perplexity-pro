"""Task 4.2: the ``attachments`` help topic, its index entry and the size budgets with both
changes' text (help-tool delta of media-inputs)."""

import re
from pathlib import Path

import jsonschema
import pytest
from fastmcp import Client
from test_help_text import tools  # noqa: F401 - the fixture

from mcp_perplexity_pro import help_text
from mcp_perplexity_pro.help_text import HelpError

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()
TIERS = {"tier_light": "x/light", "tier_standard": "x/standard", "tier_complex": "x/complex"}
SIX = ("routing", "costs", "citations", "errors", "projects", "attachments")


def topic(make_settings, **settings):
    return help_text.render_topic("attachments", make_settings(**settings))


def test_the_six_topics_are_these_and_in_this_order():
    assert help_text.TOPICS == SIX


def test_the_topic_names_the_three_forms_the_types_and_the_limits(make_settings):
    text = topic(make_settings)
    assert len(text.encode()) <= 3000 and text.isascii()
    for form in ("local path", "https URL", "data: URI"):
        assert form in text
    for kind in ("png", "jpeg", "webp", "gif", "pdf", "doc", "docx", "txt", "rtf"):
        assert kind in text
    assert "Audio and video are refused" in text
    for limit in ("10 items", "20 MiB per file", "32 MiB per call", "1 MiB inline", "30"):
        assert limit in text


def test_the_topic_explains_handling_storage_followups_replays_the_gate_and_cost(make_settings):
    text = topic(make_settings)
    assert "base64" in text and "provider fetches it" in text
    assert "file bytes are never stored" in text and "short digest" in text
    assert "follow-up keeps earlier files" in text and "replay cannot resend files" in text
    assert "perplexity_models lists each model's inputs" in text
    assert "add input tokens" in text and "PERPLEXITY_ATTACH_ROOTS" in text


@pytest.mark.parametrize("mode", ["standard", "custom"])
def test_the_topic_is_the_same_in_every_mode(make_settings, mode):
    extra = TIERS if mode == "custom" else {}
    assert topic(make_settings, routing=mode, **extra) == topic(make_settings)


def test_every_example_validates_against_its_tools_input_schema(tools):  # noqa: F811
    assert len(help_text.ATTACHMENT_EXAMPLES) == 2
    assert {name for name, _ in help_text.ATTACHMENT_EXAMPLES} == {
        "perplexity_ask",
        "perplexity_chat",
    }
    for name, arguments in help_text.ATTACHMENT_EXAMPLES:
        jsonschema.validate(arguments, tools[name][0])
        assert "attachments" in arguments


def test_the_rendered_examples_are_the_ones_validated(make_settings):
    text = topic(make_settings)
    for name, _ in help_text.ATTACHMENT_EXAMPLES:
        assert f'"name": "{name}"' in text


def test_every_dollar_figure_of_the_topic_is_in_the_readme(make_settings):
    figures = set(re.findall(r"\$\d+\.\d+", topic(make_settings)))
    assert {f for f in figures if f not in README} == set()


def test_the_index_lists_the_topic_and_stays_small(make_settings):
    text = help_text.render_index(make_settings(), sorted(help_text.TOOLS), "2.0.0")
    assert "attachments" in text.split("## Topics")[1]
    assert len(text.encode()) <= 1500 and text.isascii()


def test_the_ask_and_chat_entries_mention_attachments_in_one_line(make_settings):
    for name in ("perplexity_ask", "perplexity_chat"):
        entry = help_text.TOOLS[name]
        assert "attachments" in entry["summary"] and "\n" not in entry["summary"]
        page = help_text.render_tool(name, make_settings(), [], {})
        assert len([line for line in page.splitlines() if "topic attachments" in line]) == 1


def test_an_unknown_topic_lists_the_six(make_settings):
    with pytest.raises(HelpError) as info:
        help_text.render_topic("pricing", make_settings())
    assert str(info.value).endswith(", ".join(SIX) + ".")


def test_the_errors_topic_describes_the_local_rate_limit(make_settings):
    text = help_text.render_topic("errors", make_settings())
    line = next(x for x in text.splitlines() if x.startswith("- `rate_limited`"))
    assert "attachment" in line and "no Retry-After" in line


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"routing": "custom", **TIERS},
        {"routing": "dynamic"},
        {"routing": "dynamic", "classifier": "decisions", **TIERS},
    ],
)
def test_the_index_is_at_most_1500_bytes_and_every_topic_at_most_3000_in_every_mode(
    make_settings, settings
):
    config = make_settings(**settings)
    index = help_text.render_index(config, sorted(help_text.TOOLS), "2.0.0")
    assert len(index.encode()) <= 1500
    sizes = {name: len(help_text.render_topic(name, config).encode()) for name in help_text.TOPICS}
    assert set(sizes) == set(SIX) and all(0 < size <= 3000 for size in sizes.values()), sizes


async def test_the_help_tool_serves_the_topic(make_settings):
    from agent_support import make_world, respond_with

    world = await make_world(make_settings, respond_with("agent_fast.json"))
    try:
        async with Client(world.server) as client:
            result = await client.call_tool(
                "perplexity_help", {"action": "topic", "name": "attachments"}
            )
        assert result.structured_content["text"].startswith("# Attachments")
        bad = await world.call("perplexity_help", action="topic", name="pricing")
        assert bad.is_error and "attachments" in bad.structured_content["message"]
    finally:
        await world.aclose()

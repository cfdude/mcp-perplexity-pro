"""Task 1.4: ``agent.build_request`` takes the built attachment parts (agent-ask scenarios)."""

import dataclasses
import json
import logging

import pytest
from media_support import png
from routing_support import ask_options

from mcp_perplexity_pro import media
from mcp_perplexity_pro.agent import build_request

MODEL = "openai/gpt-6-luna"
PARTS = [
    {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
    {"type": "input_file", "filename": "r.pdf", "file_data": "BBBB"},
]


def built(options, text="What is this?", **kwargs):
    return build_request(options, text, store=False, attachments=PARTS, **kwargs)


def test_parts_become_one_user_message_with_the_text_part_first_and_the_order_kept():
    body = built(ask_options(model=MODEL, search=False))
    assert body["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "What is this?"}, *PARTS],
        }
    ]


@pytest.mark.parametrize("parts", [None, []])
def test_no_parts_builds_exactly_the_body_built_before(parts):
    options = ask_options(model=MODEL)
    assert build_request(options, "q", store=False, attachments=parts) == build_request(
        options, "q", store=False
    )
    assert build_request(options, "q", store=False, attachments=parts)["input"] == "q"


def test_a_preset_keeps_effort_and_carries_no_model_key():
    body = built(ask_options(depth="fast"))
    assert body["effort"] == "fast" and "model" not in body
    assert body["input"][0]["content"][1:] == PARTS


def test_a_model_keeps_its_search_tool_and_step_budget():
    body = built(ask_options(model=MODEL))
    assert body["model"] == MODEL and body["tools"] == [{"type": "web_search"}]
    assert body["max_steps"] == 3 and body["store"] is False


def test_json_schema_and_the_parts_travel_together():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    body = built(ask_options(depth="fast", json_schema=schema))
    assert body["response_format"]["json_schema"]["schema"] == schema
    assert body["input"][0]["content"][2]["type"] == "input_file"


def test_search_filters_with_parts_replace_the_preset_tools_as_before():
    plain = build_request(ask_options(depth="fast", domains=["python.org"]), "q", store=False)
    body = built(ask_options(depth="fast", domains=["python.org"]), "q")
    assert body["tools"] == plain["tools"]


def test_composes_with_the_chained_id():
    body = built(ask_options(model=MODEL), previous_response_id="resp_1")
    assert "reasoning" not in body and body["previous_response_id"] == "resp_1"
    assert body["input"][0]["content"][0] == {"type": "input_text", "text": "What is this?"}


def test_a_replay_list_gets_the_parts_on_its_last_item_only():
    items = [
        {"type": "message", "role": "user", "content": "first"},
        {"type": "message", "role": "assistant", "content": "answer"},
        {"type": "message", "role": "user", "content": "second"},
    ]
    body = build_request(
        ask_options(model=MODEL, search=False), items, store=False, attachments=PARTS
    )
    assert body["input"][:2] == items[:2]
    assert body["input"][2]["content"] == [{"type": "input_text", "text": "second"}, *PARTS]
    assert items[2]["content"] == "second"  # the caller's list is not changed


def test_a_replay_list_that_cannot_take_parts_is_a_caller_bug():
    options = ask_options(model=MODEL, search=False)
    items = [{"type": "message", "role": "assistant", "content": "a"}]
    with pytest.raises(ValueError):
        build_request(options, items, store=False, attachments=PARTS)


def test_the_built_parts_of_media_go_through_untouched():
    item = media.parse_attachments(["data:image/png;base64,iVBORw0KGgo="])[0]
    item = dataclasses.replace(item, data=png(), size=len(png()))
    parts = media.build_parts([item]).parts
    body = build_request(ask_options(model=MODEL), "q", store=False, attachments=parts)
    assert body["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")
    json.dumps(body)  # the body serializes


def test_building_a_request_logs_nothing_at_debug(caplog):
    caplog.set_level(logging.DEBUG)
    big = [{"type": "input_image", "image_url": "data:image/png;base64," + "Qk1h" * 400}]
    build_request(ask_options(model=MODEL), "q", store=False, attachments=big)
    assert "Qk1h" not in caplog.text and "data:image" not in caplog.text

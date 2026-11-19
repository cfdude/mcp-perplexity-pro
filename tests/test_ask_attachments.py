"""Task 1.5: ``perplexity_ask`` takes ``attachments``: parsing, the local read and the parts.

The gate and the attachment hint are task 2.3; here every call that parses is sent.
"""

import base64
import logging

import pytest
from agent_support import make_world, respond_with
from media_support import pdf, png

from mcp_perplexity_pro import media

TOOL = "perplexity_ask"
MODEL = "openai/gpt-6-luna"


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder=None, **settings):
        w = await make_world(
            make_settings, responder or respond_with("agent_fast.json"), **settings
        )
        made.append(w)
        return w

    yield build
    for w in made:
        await w.aclose()


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def content(w, n=0):
    return w.bodies()[n]["input"][0]["content"]


def category(result):
    assert result.is_error
    return result.structured_content["category"]


async def nothing_happened(w):
    assert w.requests == []
    assert await w.count("usage_events") == 0
    assert await w.count("projects") == 0


# --- the parameter ----------------------------------------------------------------------------


async def test_the_parameter_is_a_list_of_strings_with_a_short_description(world):
    from fastmcp import Client

    w = await world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    spec = tool.input_schema["properties"]["attachments"]
    assert {"type": "array", "items": {"type": "string"}} in spec["anyOf"]
    assert len(spec["description"]) <= 100
    assert "token" in spec["description"]  # the cost note
    assert "retain" not in spec["description"].lower()
    assert "attachments" not in tool.input_schema["required"]


# --- the request ------------------------------------------------------------------------------


async def test_a_png_path_is_one_message_of_parts_and_one_event_is_stored(world, tmp_path):
    w = await world()
    path = write(tmp_path, "shot.png", png())
    result = await w.call(TOOL, query="What colour is this?", model=MODEL, attachments=[path])
    assert not result.is_error, result.content
    parts = content(w)
    assert parts[0] == {"type": "input_text", "text": "What colour is this?"}
    assert parts[1]["type"] == "input_image"
    encoded = parts[1]["image_url"].removeprefix("data:image/png;base64,")
    assert base64.b64decode(encoded) == png()
    assert len(await w.events()) == 1


async def test_a_preset_with_a_png_carries_effort_and_no_model(world, tmp_path):
    w = await world()
    path = write(tmp_path, "shot.png", png())
    result = await w.call(TOOL, query="q", depth="fast", attachments=[path])
    assert not result.is_error, result.content
    body = w.bodies()[0]
    assert body["effort"] == "fast" and "model" not in body
    assert body["input"][0]["content"][1]["type"] == "input_image"


async def test_every_form_and_the_order_are_kept(world, tmp_path):
    w = await world()
    path = write(tmp_path, "r.pdf", pdf())
    inline = "data:image/png;base64," + base64.b64encode(png()).decode()
    result = await w.call(
        TOOL,
        query="q",
        model=MODEL,
        attachments=[path, "https://example.com/pic.png", inline, "https://example.com/r.pdf"],
    )
    assert not result.is_error, result.content
    kinds = [
        (p["type"], "file_url" in p or p.get("image_url", "").startswith("https"))
        for p in content(w)[1:]
    ]
    assert kinds == [
        ("input_file", False),
        ("input_image", True),
        ("input_image", False),
        ("input_file", True),
    ]
    assert content(w)[1]["filename"] == "r.pdf"
    assert content(w)[4]["file_url"] == "https://example.com/r.pdf"


async def test_json_schema_and_a_document_travel_together_and_search_is_kept(world, tmp_path):
    w = await world()
    path = write(tmp_path, "r.pdf", pdf())
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    result = await w.call(TOOL, query="q", model=MODEL, json_schema=schema, attachments=[path])
    assert not result.is_error, result.content
    body = w.bodies()[0]
    assert body["response_format"]["json_schema"]["schema"] == schema
    assert body["tools"] == [{"type": "web_search"}]
    assert content(w)[1]["type"] == "input_file"


@pytest.mark.parametrize("empty", [[], None])
async def test_an_empty_list_builds_the_request_a_call_without_attachments_builds(world, empty):
    w = await world()
    kwargs = {} if empty is None else {"attachments": empty}
    assert not (await w.call(TOOL, query="plain", model=MODEL, **kwargs)).is_error
    assert not (await w.call(TOOL, query="plain", model=MODEL)).is_error
    first, second = w.bodies()
    assert first == second and first["input"] == "plain"


# --- validation before anything is stored -----------------------------------------------------


async def test_a_missing_file_fails_before_the_project_exists(world, tmp_path):
    w = await world()
    result = await w.call(
        TOOL, query="q", model=MODEL, project="new-project", attachments=[str(tmp_path / "no.png")]
    )
    assert category(result) == "not_found"
    assert "attachments[0]" in result.structured_content["message"]
    await nothing_happened(w)


async def test_an_integer_item_names_attachments_and_does_not_quote_the_value(world):
    w = await world()
    result = await w.call(TOOL, query="q", model=MODEL, attachments=[87654321])
    assert category(result) == "invalid_request"
    message = result.structured_content["message"]
    assert "attachments" in message and "87654321" not in message
    await nothing_happened(w)


async def test_a_bad_item_fails_naming_its_position(world):
    w = await world()
    result = await w.call(
        TOOL, query="q", model=MODEL, attachments=["https://a.example/x.png", "x.png"]
    )
    assert category(result) == "invalid_request"
    assert "attachments[1]" in result.structured_content["message"]
    await nothing_happened(w)


async def test_eleven_items_fail_naming_the_limit(world):
    w = await world()
    result = await w.call(
        TOOL, query="q", model=MODEL, attachments=["https://example.com/a.png"] * 11
    )
    assert category(result) == "invalid_request" and "10" in result.structured_content["message"]
    await nothing_happened(w)


async def test_bytes_that_are_not_the_extensions_type_fail_before_a_request(world, tmp_path):
    w = await world()
    path = write(tmp_path, "fake.png", b"not a png at all")
    result = await w.call(TOOL, query="q", model=MODEL, attachments=[path])
    assert category(result) == "invalid_request"
    await nothing_happened(w)


async def test_audio_is_refused_locally(world, tmp_path):
    w = await world()
    result = await w.call(
        TOOL, query="q", model=MODEL, attachments=[write(tmp_path, "a.wav", b"RIFF")]
    )
    assert category(result) == "invalid_request"
    assert "audio" in result.structured_content["message"].lower()
    await nothing_happened(w)


async def test_a_tier_error_beats_the_attachment_read(world, tmp_path):
    w = await world(routing="dynamic")
    result = await w.call(TOOL, query="q", tier="huge", attachments=[str(tmp_path / "no.png")])
    assert category(result) == "invalid_request"
    assert "tier" in result.structured_content["message"]
    await nothing_happened(w)


async def test_a_bad_attachment_beats_the_decisions_classifier(world, tmp_path):
    w = await world(routing="dynamic", classifier="decisions")
    result = await w.call(TOOL, query="q", attachments=[str(tmp_path / "no.png")])
    assert result.is_error
    assert w.requests == []  # no Decisions request, no model request
    assert await w.count("usage_events") == 0


async def test_two_files_over_the_total_fail_naming_the_total_and_send_nothing(
    world, tmp_path, monkeypatch
):
    monkeypatch.setattr(media, "MAX_TOTAL_BYTES", 1024 * 1024)
    w = await world()
    one = write(tmp_path, "a.pdf", b"%PDF-" + b"0" * 700_000)
    two = write(tmp_path, "b.pdf", b"%PDF-" + b"0" * 700_000)
    result = await w.call(TOOL, query="q", model=MODEL, attachments=[one, two])
    assert category(result) == "invalid_request"
    assert "total" in result.structured_content["message"]
    await nothing_happened(w)


async def test_a_local_path_is_refused_over_http_unless_the_roots_are_set(world, tmp_path):
    w = await world()
    path = write(tmp_path, "shot.png", png())
    w.server.app.attach.http = True
    result = await w.call(TOOL, query="q", model=MODEL, attachments=[path])
    assert category(result) == "invalid_request"
    assert "PERPLEXITY_ATTACH_ROOTS" in result.structured_content["message"]
    await nothing_happened(w)
    w2 = await world(attach_roots=str(tmp_path))
    w2.server.app.attach.http = True
    assert not (await w2.call(TOOL, query="q", model=MODEL, attachments=[path])).is_error


async def test_the_byte_share_is_released_after_a_call_and_after_a_failure(world, tmp_path):
    w = await world()
    limiter = w.server.app.attach.limiter
    path = write(tmp_path, "shot.png", png())
    assert not (await w.call(TOOL, query="q", model=MODEL, attachments=[path])).is_error
    assert limiter.used == 0
    bad = write(tmp_path, "bad.png", b"not a png")
    assert (await w.call(TOOL, query="q", model=MODEL, attachments=[bad])).is_error
    assert limiter.used == 0


async def test_an_upstream_failure_after_the_read_releases_the_share(world, tmp_path):
    w = await world(respond_with("agent_fast.json", status=500))
    path = write(tmp_path, "shot.png", png())
    assert (await w.call(TOOL, query="q", model=MODEL, attachments=[path])).is_error
    assert w.server.app.attach.limiter.used == 0


# --- logging ----------------------------------------------------------------------------------


async def test_debug_logging_holds_no_body_and_only_position_kind_type_size_and_digest(
    world, tmp_path, caplog
):
    caplog.set_level(logging.DEBUG)
    w = await world()
    path = write(tmp_path, "secret-name.png", png())
    assert not (await w.call(TOOL, query="q", model=MODEL, attachments=[path])).is_error
    text = caplog.text
    encoded = base64.b64encode(png()).decode()
    assert encoded[:40] not in text and "data:image/png" not in text
    assert "secret-name" not in text and str(tmp_path) not in text
    assert f"attachment 0: image image/png {len(png())} bytes sha256 " in text


def test_the_parse_hook_returns_the_kinds_of_the_items_and_nothing_for_none():
    from mcp_perplexity_pro import call_flow

    assert call_flow.parse_attachments(None) == frozenset()
    assert call_flow.parse_attachments([]) == frozenset()
    mixed = ["https://example.com/a.png", "https://example.com/b.pdf"]
    assert call_flow.parse_attachments(mixed) == {"image", "document"}
    assert call_flow.parse_attachments(mixed[:1]) == {"image"}


def test_the_policy_carries_the_roots_the_transport_and_the_data_directory(make_settings, tmp_path):
    from mcp_perplexity_pro.media_read import AttachState

    settings = make_settings(attach_roots=f"{tmp_path}")
    state = AttachState()
    policy = state.policy(settings)
    assert policy.roots == (str(tmp_path),) and policy.http is False
    assert policy.data_dir == settings.data_dir
    state.http = True
    assert state.policy(settings).http is True


@pytest.mark.parametrize(("transport", "http"), [("http", True), ("stdio", False)])
def test_run_sets_the_transport_flag_before_serving(monkeypatch, transport, http):
    import types

    from mcp_perplexity_pro import __main__ as entry

    server = types.SimpleNamespace(
        app=types.SimpleNamespace(attach=types.SimpleNamespace(http=None))
    )
    seen = []

    async def fake(*args, **kwargs):
        seen.append(server.app.attach.http)

    monkeypatch.setattr(entry, "_run_http", fake)
    monkeypatch.setattr(entry, "_run_stdio", fake)
    entry.run(server, None, transport=transport)
    assert seen == [http]


async def test_the_base64_and_hash_work_runs_off_the_event_loop(world, tmp_path, monkeypatch):
    import threading

    from mcp_perplexity_pro import media

    seen = []
    real = media.build_parts

    def spy(items):
        seen.append(threading.current_thread() is threading.main_thread())
        return real(items)

    monkeypatch.setattr(media, "build_parts", spy)
    w = await world()
    path = write(tmp_path, "shot.png", png())
    assert not (await w.call(TOOL, query="q", model=MODEL, attachments=[path])).is_error
    assert seen == [False]


async def test_a_signed_url_path_never_reaches_a_usage_row_or_a_log(world, caplog):
    import httpx2

    url = "https://files.example.com/private/PATHTOKEN/report.pdf?sig=QUERYTOKEN"

    def echo(request, n):
        message = f"cannot fetch {url}"
        body = {"error": {"message": message, "type": "invalid_request", "code": 400}}
        return httpx2.Response(400, json=body)

    caplog.set_level(logging.DEBUG)
    w = await world(echo)
    result = await w.call(TOOL, query="q", model=MODEL, attachments=[url])
    assert result.is_error
    assert "QUERYTOKEN" not in str(result.content)  # the caller's error: no query either
    rows = await w.rows("SELECT * FROM usage_events")
    persisted = repr(rows) + caplog.text
    for secret in ("PATHTOKEN", "QUERYTOKEN"):
        assert secret not in persisted, secret

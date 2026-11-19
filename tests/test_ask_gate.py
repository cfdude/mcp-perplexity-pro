"""Task 2.3: the model gate, the preset rule and the attachment hint on ``perplexity_ask``."""

import pytest
from agent_support import fixture, make_world, respond_body, respond_with
from media_support import pdf, png

from mcp_perplexity_pro import media_gate
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.rules import Classification
from mcp_perplexity_pro.tools import ask as ask_tool

TOOL = "perplexity_ask"
ACCEPTING = "openai/gpt-6-luna"  # the baseline records image and document accepted
REFUSES_DOCUMENTS = "xai/grok-4.3"  # the baseline records a named route refusal for documents
TIERS = {"tier_light": REFUSES_DOCUMENTS, "tier_standard": ACCEPTING, "tier_complex": ACCEPTING}


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


@pytest.fixture
def files(tmp_path):
    def write(name, data):
        path = tmp_path / name
        path.write_bytes(data)
        return str(path)

    return write


def message(result):
    assert result.is_error
    return result.structured_content["message"]


async def nothing_happened(w):
    assert w.requests == []
    assert await w.count("usage_events") == 0
    assert await w.count("projects") == 0


# --- the gate on an explicit model ------------------------------------------------------------


async def test_a_model_the_matrix_refuses_is_not_sent_the_document(world, files):
    w = await world()
    result = await w.call(
        TOOL, query="q", model=REFUSES_DOCUMENTS, attachments=[files("r.pdf", pdf())]
    )
    text = message(result)
    assert result.structured_content["category"] == "invalid_request"
    assert text.startswith("model:") and REFUSES_DOCUMENTS in text and "document" in text
    assert "Models recorded as accepting document:" in text
    await nothing_happened(w)


def test_at_most_five_accepting_models_are_named():
    from mcp_perplexity_pro import matrix

    text = media_gate.blocked(
        ask_tool.resolve(world_settings(), model=REFUSES_DOCUMENTS),
        frozenset({"document"}),
        matrix.load_baseline(),
    )
    listed = text.split("accepting document:")[1].split(". perplexity_models")[0]
    assert 1 <= len([m for m in listed.split(",") if m.strip()]) <= 5


def world_settings():
    from mcp_perplexity_pro.settings import Settings

    return Settings(api_key="test-dummy-api-key")


async def test_a_text_call_to_a_refusing_model_is_unaffected(world):
    w = await world()
    assert not (await w.call(TOOL, query="q", model=REFUSES_DOCUMENTS)).is_error
    assert not (await w.call(TOOL, query="q", model=REFUSES_DOCUMENTS, attachments=[])).is_error
    assert len(w.bodies()) == 2


async def test_an_unknown_model_is_sent_the_attachment_and_the_api_decides(world, files):
    w = await world()
    result = await w.call(
        TOOL, query="q", model="vendor/not-in-the-matrix", attachments=[files("a.png", png())]
    )
    assert not result.is_error, result.content
    assert w.bodies()[0]["input"][0]["content"][1]["type"] == "input_image"


async def test_a_model_that_accepts_the_kinds_is_sent_them(world, files):
    w = await world()
    path = files("r.pdf", pdf())
    assert not (await w.call(TOOL, query="q", model=ACCEPTING, attachments=[path])).is_error


# --- tier models and the default route --------------------------------------------------------


async def test_a_tier_model_that_refuses_fails_naming_it_and_the_kind(world, files):
    w = await world(routing="custom", **TIERS)
    result = await w.call(TOOL, query="q", tier="light", attachments=[files("r.pdf", pdf())])
    text = message(result)
    assert REFUSES_DOCUMENTS in text and "document" in text and "tier light" in text
    await nothing_happened(w)


async def test_an_unknown_tier_model_is_sent(world, files):
    w = await world(
        routing="custom",
        tier_light="vendor/unknown-l",
        tier_standard="vendor/unknown-s",
        tier_complex="vendor/unknown-c",
    )
    result = await w.call(TOOL, query="q", tier="light", attachments=[files("a.png", png())])
    assert not result.is_error, result.content
    assert w.bodies()[0]["model"] == "vendor/unknown-l"


async def test_the_default_route_is_gated_too(world, files):
    w = await world(model=REFUSES_DOCUMENTS)
    result = await w.call(TOOL, query="q", attachments=[files("r.pdf", pdf())])
    assert REFUSES_DOCUMENTS in message(result)
    await nothing_happened(w)


# --- presets ----------------------------------------------------------------------------------


async def test_a_verified_preset_is_sent_and_an_unverified_one_fails_locally(world, files):
    w = await world()
    assert not (
        await w.call(TOOL, query="q", depth="fast", attachments=[files("a.png", png())])
    ).is_error
    assert w.bodies()[0]["effort"] == "fast" and "model" not in w.bodies()[0]
    result = await w.call(TOOL, query="q", depth="low", attachments=[files("r.pdf", pdf())])
    text = message(result)
    assert "depth" in text and "'low'" in text and "document" in text
    assert len(w.bodies()) == 1  # nothing more was sent
    assert len(await w.events()) == 1


# --- order: the gate before the classifier and again after it ---------------------------------


@pytest.fixture
def classify(monkeypatch):
    calls = []

    async def fake(app, text, *, project, tool):
        calls.append(text)
        return fake.verdict

    fake.verdict = Classification("complex", "stub", "decisions")
    monkeypatch.setattr(ask_tool, "classify_dynamic", fake)
    return fake, calls


async def test_a_call_no_tier_can_carry_fails_before_the_decisions_request(world, files, classify):
    _, calls = classify
    w = await world(
        routing="dynamic",
        classifier="decisions",
        tier_light=REFUSES_DOCUMENTS,
        tier_standard=REFUSES_DOCUMENTS,
        tier_complex=REFUSES_DOCUMENTS,
    )
    result = await w.call(TOOL, query="q", attachments=[files("r.pdf", pdf())])
    assert REFUSES_DOCUMENTS in message(result)
    assert calls == [] and w.requests == []


async def test_a_call_another_tier_can_carry_waits_for_the_classifier(world, files, classify):
    fake, calls = classify
    fake.verdict = Classification("standard", "stub", "decisions")
    w = await world(routing="dynamic", classifier="decisions", **TIERS)
    # the rules would pick light (a short lookup), whose model refuses; the classifier says
    # standard, whose model accepts, so the call is not refused before it
    query = "what is the capital of France?"
    result = await w.call(TOOL, query=query, attachments=[files("r.pdf", pdf())])
    assert not result.is_error, result.content
    assert calls == [query] and w.bodies()[0]["model"] == ACCEPTING


async def test_a_reclassified_tier_whose_pin_refuses_fails_after_the_classifier(
    world, files, classify
):
    fake, calls = classify
    pins = {"tier_light": ACCEPTING, "tier_standard": ACCEPTING, "tier_complex": REFUSES_DOCUMENTS}
    w = await world(routing="dynamic", classifier="decisions", **pins)
    result = await w.call(TOOL, query="hi", attachments=[files("r.pdf", pdf())])
    assert REFUSES_DOCUMENTS in message(result) and "document" in message(result)
    assert calls == ["hi"]  # the classifier ran, the model request did not
    assert w.requests == []


async def test_a_tentative_route_the_classifier_keeps_is_still_gated(world, files, classify):
    fake, calls = classify
    fake.verdict = Classification("light", "stub", "decisions")  # the same tier the rules chose
    w = await world(routing="dynamic", classifier="decisions", **TIERS)
    result = await w.call(TOOL, query="hi", attachments=[files("r.pdf", pdf())])
    assert REFUSES_DOCUMENTS in message(result) and w.requests == []


# --- hints ------------------------------------------------------------------------------------


def error_body(text):
    return {"error": {"message": text, "type": "invalid_request", "code": 400}}


async def test_the_generic_400_gets_the_attachment_hint(world, files):
    w = await world(respond_body(error_body("invalid request"), status=400))
    result = await w.call(
        TOOL, query="q", model="vendor/unknown", attachments=[files("a.png", png())]
    )
    text = message(result)
    assert result.structured_content["category"] == "invalid_request"
    assert "invalid request" in text and "may not accept image" in text
    assert "perplexity_models" in text


async def test_a_descriptive_400_keeps_its_text_and_names_the_kinds(world, files):
    body = "the selected model route does not support this document type or source"
    w = await world(respond_body(error_body(body), status=400))
    result = await w.call(
        TOOL, query="q", model="vendor/unknown", attachments=[files("r.pdf", pdf())]
    )
    text = message(result)
    assert body in text and "carried document attachments" in text


async def test_a_model_that_is_gone_is_not_blamed_on_the_attachment(world, files):
    gone = "validation failed: model vendor/retired is not supported"
    w = await world(respond_body(error_body(gone), status=400))
    result = await w.call(
        TOOL, query="q", model="vendor/retired", attachments=[files("a.png", png())]
    )
    text = message(result)
    assert "model vendor/retired is not served" in text
    assert "may not accept" not in text and "carried" not in text


async def test_the_model_gone_text_is_a_seam_the_default_of_which_is_plain(
    world, files, monkeypatch
):
    gone = "validation failed: model vendor/retired is not supported"
    w = await world(respond_body(error_body(gone), status=400))
    monkeypatch.setattr(
        media_gate,
        "model_gone_hint",
        lambda exc, model: PerplexityError("invalid_request", f"try the live {model} family"),
    )
    result = await w.call(
        TOOL, query="q", model="vendor/retired", attachments=[files("a.png", png())]
    )
    assert "try the live vendor/retired family" in message(result)


async def test_a_rate_limit_and_a_server_error_are_not_hinted(world, files):
    for status, category in ((429, "rate_limited"), (500, "upstream_failure")):
        w = await world(respond_body({"error": {"message": "slow down"}}, status=status))
        result = await w.call(
            TOOL, query="q", model="vendor/unknown", attachments=[files("a.png", png())]
        )
        assert result.structured_content["category"] == category
        assert "attachment" not in message(result).lower()


async def test_the_attachment_hint_beats_the_schema_hint(world, files):
    w = await world(respond_body(error_body("invalid request"), status=400))
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    result = await w.call(
        TOOL,
        query="q",
        model="vendor/unknown",
        json_schema=schema,
        attachments=[files("a.png", png())],
    )
    text = message(result)
    assert "may not accept image" in text and "json_schema is invalid" not in text
    plain = await w.call(TOOL, query="q", model="vendor/unknown", json_schema=schema)
    assert "json_schema is invalid" in message(plain)  # unchanged without attachments


async def test_a_failed_run_with_a_refusal_keeps_its_category_and_gets_the_hint(world, files):
    body = fixture("agent_document_failed_refusal.json")
    w = await world(respond_body(body))
    result = await w.call(
        TOOL, query="q", model="anthropic/claude-opus-5", attachments=[files("r.pdf", pdf())]
    )
    text = message(result)
    assert result.structured_content["category"] == "unexpected_response"
    assert "refused the document attachment" in text and "another model" in text
    assert len(await w.events()) == 1  # recorded as the run's status, once


async def test_a_failed_run_without_a_document_gets_no_refusal_hint(world, files):
    body = fixture("agent_document_failed_refusal.json")
    w = await world(respond_body(body))
    result = await w.call(
        TOOL, query="q", model="anthropic/claude-opus-5", attachments=[files("a.png", png())]
    )
    assert "refused the" not in message(result)
    plain = await w.call(TOOL, query="q", model="anthropic/claude-opus-5")
    assert "refused the" not in message(plain)

"""Task 3.3 (py-decisions-tool): ``perplexity_decide`` through ``build_server``."""

import json

import httpx2
import jsonschema
import pytest
from agent_support import fixture, make_world, respond_body, respond_with
from fastmcp import Client

TOOL = "perplexity_decide"
THREE = fixture("decisions_three_questions.meta.json")["request"]


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder=None, **settings):
        w = await make_world(
            make_settings, responder or respond_with("decisions_three_questions.json"), **settings
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


async def test_structured_content_validates_and_the_text_has_one_line_per_question(world):
    w = await world()
    result = await w.call(TOOL, state=THREE["state"], questions=THREE["questions"])
    assert not result.is_error
    async with Client(w.server) as client:
        schema = next(t for t in await client.list_tools() if t.name == TOOL).output_schema
    jsonschema.validate(result.structured_content, schema)
    text = result.content[0].text
    assert "urgent: noul" in text and "area: choice export" in text and "severity: score" in text
    assert "Usage:" in text


async def test_the_recorded_response_costs_6940_nano_computed_and_is_one_event(world):
    w = await world()
    result = await w.call(TOOL, state=THREE["state"], questions=THREE["questions"])
    sc = result.structured_content
    assert (sc["cost_usd"], sc["cost_source"], sc["project"]) == (
        "0.00000694",
        "computed",
        "default",
    )
    assert (sc["input_tokens"], sc["output_tokens"], sc["model"]) == (
        347,
        3,
        "pplx-decider-v1.1-27b",
    )
    assert list(sc["answers"]) == ["urgent", "area", "severity"]
    assert w.bodies() == [THREE]  # exactly model, state and questions, default model sent
    ((tool, api, status, preset, model, rid, project, nano, source),) = await w.events()
    assert (tool, api, status, preset, model, rid, project, nano, source) == (
        TOOL, "decisions", "ok", None, "pplx-decider-v1.1-27b", None, "default", 6940, "computed",
    )  # fmt: skip


async def test_the_older_model_is_sent_when_asked(world):
    w = await world(respond_with("decisions_model_v1.json"))
    req = fixture("decisions_model_v1.meta.json")["request"]
    result = await w.call(TOOL, state=req["state"], questions=req["questions"], model=req["model"])
    assert not result.is_error and w.bodies() == [req]


async def test_a_named_project_is_used(world):
    w = await world()
    ok = await w.call(
        TOOL, state="s", questions={"q": {"type": "noul", "instructions": "y"}}, project="alpha"
    )
    assert ok.structured_content["project"] == "alpha"


async def test_a_bad_project_name_does_nothing(world):
    w = await world()
    bad = await w.call(
        TOOL, state="s", questions={"q": {"type": "noul", "instructions": "y"}}, project="../x"
    )
    assert category(bad) == "invalid_request"
    await nothing_happened(w)


async def test_a_missing_answer_is_left_out_with_a_warning(world):
    body = fixture("decisions_three_questions.json")
    del body["answers"]["area"]
    w = await world(respond_body(body))
    sc = (await w.call(TOOL, state=THREE["state"], questions=THREE["questions"])).structured_content
    assert list(sc["answers"]) == ["urgent", "severity"]
    assert any("'area'" in x for x in sc["warnings"])


async def test_a_response_without_usage_has_unknown_cost_and_a_none_event(world):
    body = fixture("decisions_noul.json")
    del body["usage"]
    w = await world(respond_body(body))
    req = fixture("decisions_noul.meta.json")["request"]
    sc = (await w.call(TOOL, state=req["state"], questions=req["questions"])).structured_content
    assert sc["cost_usd"] is None and sc["cost_source"] == "none"
    ((*_, nano, source),) = await w.events()
    assert (nano, source) == (0, "none")


async def test_the_apis_400_comes_back_with_its_message(world):
    w = await world(respond_with("decisions_129_questions_400.json", 400))
    result = await w.call(TOOL, state="s", questions={"q": {"type": "noul", "instructions": "y"}})
    assert category(result) == "invalid_request"
    assert "between 1 and 128 questions" in result.structured_content["message"]


NOUL = {"type": "noul", "instructions": "y"}
LOCAL_REFUSALS = [
    {"state": ""},
    {"state": "   "},
    {"state": {}},
    {"state": [{"type": "image_url", "image_url": {"url": "x"}}]},
    {"questions": {}},
    {"questions": {f"q{i}": NOUL for i in range(33)}},
    {"questions": {"q": {"type": "noul"}}},
    {"questions": {"q": {"type": "choice", "criteria": {}}}},
    {"questions": {"q": {"type": "score", "criteria": list("abcdefghijk")}}},
    {"model": "pplx-decider-nope"},
]


@pytest.mark.parametrize("arguments", LOCAL_REFUSALS, ids=lambda a: json.dumps(a)[:40])
async def test_every_local_refusal_is_invalid_request_with_nothing_sent_or_stored(world, arguments):
    w = await world()
    result = await w.call(TOOL, **{"state": "s", "questions": {"q": NOUL}, **arguments})
    assert category(result) == "invalid_request"
    await nothing_happened(w)


async def test_a_response_of_the_wrong_http_kind_fails_without_internal_error(world):
    w = await world(lambda request, n: httpx2.Response(200, json={"model": "x"}))
    result = await w.call(TOOL, state="s", questions={"q": NOUL})
    assert category(result) == "unexpected_response"
    ((_, _, status, *_),) = await w.events()
    assert status == "unexpected_response"


# --- api-drift-2026-10 task 3.1: the newer models and aliases -------------------------------------

from mcp_perplexity_pro.decisions import DEFAULT_MODEL, MODELS  # noqa: E402

NEW_NAMES = [m for m in MODELS if m not in ("pplx-decider-v1.1-27b", "pplx-decider-v1-27b")]
FLASH_NAMES = [m for m in MODELS if "flash" in m]


def echoing(model):
    """The recorded three-question response, with ``model`` set (or removed with ``None``)."""
    body = fixture("decisions_three_questions.json")
    if model is None:
        body.pop("model")
    else:
        body["model"] = model
    return body


def test_the_accepted_names_are_the_eight_of_the_spec_and_the_default_is_unchanged():
    assert len(MODELS) == 8 and DEFAULT_MODEL == "pplx-decider-v1.1-27b"
    assert set(NEW_NAMES) == {
        "pplx-decider-v1.2",
        "pplx-decider-flash-v1.2",
        "pplx-decider-latest",
        "pplx-decider-flash-latest",
        "perplexity/pplx-decider-latest",
        "perplexity/pplx-decider-flash-latest",
    }


@pytest.mark.parametrize("name", NEW_NAMES)
async def test_each_new_name_is_carried_verbatim_in_the_request(world, name):
    w = await world(respond_body(echoing(name)))
    result = await w.call(TOOL, state=THREE["state"], questions=THREE["questions"], model=name)
    assert not result.is_error, result.content
    assert w.bodies() == [{**THREE, "model": name}]


@pytest.mark.parametrize("name", MODELS)
async def test_every_accepted_name_is_stored_verbatim_by_the_recorder(world, name):
    w = await world(respond_body(echoing(name)))
    await w.call(TOOL, state=THREE["state"], questions=THREE["questions"], model=name)
    ((_, _, status, _, model, *_),) = await w.events()
    assert (status, model) == ("ok", name)
    rows = await w.rows("SELECT model FROM usage_events")
    assert rows == [(name,)]


async def test_a_flash_request_costs_3470_nano_even_if_the_response_echoes_another_name(world):
    w = await world()  # the recorded response echoes pplx-decider-v1.1-27b, 347 input tokens
    result = await w.call(
        TOOL,
        state=THREE["state"],
        questions=THREE["questions"],
        model="pplx-decider-flash-v1.2",
    )
    sc = result.structured_content
    assert (sc["cost_usd"], sc["cost_source"], sc["input_tokens"]) == (
        "0.00000347",
        "computed",
        347,
    )
    ((*_, nano, source),) = await w.events()
    assert (nano, source) == (3470, "computed")


@pytest.mark.parametrize("name", FLASH_NAMES)
@pytest.mark.parametrize("echo", ["pplx-decider-flash-v1.2", "pplx-decider-v1.2", None])
async def test_a_flash_alias_is_priced_by_the_requests_name_whatever_the_response_says(
    world, name, echo
):
    w = await world(respond_body(echoing(echo)))
    result = await w.call(TOOL, state=THREE["state"], questions=THREE["questions"], model=name)
    assert result.structured_content["cost_usd"] == "0.00000347"
    ((*_, nano, source),) = await w.events()
    assert (nano, source) == (3470, "computed")


@pytest.mark.parametrize("name", [m for m in MODELS if "flash" not in m])
async def test_every_other_accepted_name_costs_6940_nano(world, name):
    w = await world(respond_body(echoing(name)))
    result = await w.call(TOOL, state=THREE["state"], questions=THREE["questions"], model=name)
    assert result.structured_content["cost_usd"] == "0.00000694"
    ((*_, nano, source),) = await w.events()
    assert (nano, source) == (6940, "computed")


@pytest.mark.parametrize("name", ["pplx-decider-v1.3", "pplx-decider-latest ", "decider-latest"])
async def test_an_unlisted_name_is_invalid_request_before_any_call(world, name):
    w = await world()
    result = await w.call(TOOL, state="s", questions={"q": NOUL}, model=name)
    assert category(result) == "invalid_request" and "model" in result.structured_content["message"]
    await nothing_happened(w)


async def test_the_listing_names_the_models_and_the_flash_price(world):
    w = await world()
    async with Client(w.server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    desc = " ".join(tool.description.split())
    assert "$0.01 for the flash models" in desc
    model_text = tool.input_schema["properties"]["model"]["description"]
    assert all(name.removeprefix("perplexity/") in model_text for name in MODELS)

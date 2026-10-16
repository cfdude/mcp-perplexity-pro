"""Task 1.2 (routing-decisions-classifier): ``classify_dynamic`` against ``MockTransport`` and the
recorded ``decisions_tier_*`` fixtures, with a real engine so the usage events are real.

Observed on 2026-10-15 (live capture, ``decisions_tier_*.meta.json``): the lookup prompt got
choice ``light`` with probability 0.931 and confidence 0.897; the ordinary question got
``complex`` with probability 0.636 and confidence 0.454 (the decider put it above the rules'
tier); the long analytical task got ``complex`` with probability 0.999 and confidence 0.999.
"""

import asyncio
import json
import logging
from types import SimpleNamespace

import httpx2
import pytest
from fixture_support import FIXTURE_DIR
from sqlalchemy import text
from usage_support import Upstream

from mcp_perplexity_pro import decisions, routing_decisions, rules
from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.routing_decisions import CRITERIA, classify_dynamic
from mcp_perplexity_pro.storage.engine import create_engine_for
from mcp_perplexity_pro.storage.migrate import migrate

SECRET = "hunter2"
TIERS = ("light", "standard", "complex")


def sidecar(tier):
    return json.loads((FIXTURE_DIR / f"decisions_tier_{tier}.meta.json").read_text())


def fixture(tier):
    return json.loads((FIXTURE_DIR / f"decisions_tier_{tier}.json").read_text())


LIGHT_PROMPT = sidecar("light")["request"]["state"]
COMPLEX_PROMPT = sidecar("complex")["request"]["state"]
SHORT_PROMPT = "Tell me about caching."  # the rules say standard


def serve(body, status=200, headers=None):
    return lambda request, n: httpx2.Response(status, json=body, headers=headers)


def answer(choice, probabilities=None, confidence=None, **extra):
    tier = {"type": "choice", "choice": choice, **extra}
    if probabilities is not None:
        tier["probabilities"] = probabilities
    if confidence is not None:
        tier["confidence"] = confidence
    return {
        "model": "pplx-decider-v1.1-27b",
        "answers": {"tier": tier},
        "usage": {"input_tokens": 100, "output_tokens": 1},
    }


def probs(light=0.0, standard=0.0, complex_=0.0):
    return {"light": light, "standard": standard, "complex": complex_}


@pytest.fixture
async def world(make_settings):
    made = []

    async def build(responder, **settings):
        cfg = make_settings(db_busy_timeout=0.4, **{"max_attempts": 1, **settings})
        migrate(cfg)
        engine = create_engine_for(cfg)
        upstream = Upstream(responder)
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
        client = PerplexityClient(cfg, http=http)
        made.append((http, engine))
        return SimpleNamespace(settings=cfg, client=client, engine=engine), upstream

    yield build
    for http, engine in made:
        await http.aclose()
        await engine.dispose()


async def events(app):
    async with app.engine.connect() as conn:
        rows = await conn.execute(text("SELECT * FROM usage_events ORDER BY id"))
        return [dict(r._mapping) for r in rows]


async def classify(app, prompt, tool="perplexity_ask", project="alpha"):
    return await classify_dynamic(app, prompt, project=project, tool=tool)


# --- the request ------------------------------------------------------------------------------


@pytest.mark.parametrize("tier", TIERS)
def test_the_criteria_are_the_ones_the_fixtures_were_captured_with(tier):
    request = sidecar(tier)["request"]
    assert request["questions"] == {"tier": {"type": "choice", "criteria": CRITERIA}}
    assert request["model"] == decisions.DEFAULT_MODEL
    assert all(c.isascii() and "\n" not in c for c in CRITERIA.values())


async def test_the_request_is_one_tier_choice_over_the_first_4000_characters(world):
    prompt = "a" * 3999 + "b" + "c" * 2000  # 6000 characters
    app, upstream = await world(serve(fixture("light")))
    sent = []
    upstream.responder = lambda request, n: (
        sent.append(json.loads(request.content)) or httpx2.Response(200, json=fixture("light"))
    )
    await classify(app, prompt)
    assert upstream.calls == 1
    (body,) = sent
    assert body["state"] == prompt[:4000] and body["state"].endswith("b")
    assert body["model"] == "pplx-decider-v1.1-27b"
    assert body["questions"] == {"tier": {"type": "choice", "criteria": CRITERIA}}
    assert list(body["questions"]["tier"]["criteria"]) == ["light", "standard", "complex"]


# --- the answer -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "prompt", "expected"),
    [
        ("light", LIGHT_PROMPT, "light"),
        ("standard", sidecar("standard")["request"]["state"], "complex"),  # observed answer
        ("complex", COMPLEX_PROMPT, "complex"),
    ],
)
async def test_the_recorded_answer_picks_the_tier(world, tier, prompt, expected):
    app, _ = await world(serve(fixture(tier)))
    result = await classify(app, prompt)
    assert (result.tier, result.classifier) == (expected, "decisions")
    assert expected in result.reason and "decisions" in result.reason


async def test_the_reason_names_the_probability_of_the_chosen_option(world):
    app, _ = await world(serve(fixture("complex")))
    result = await classify(app, COMPLEX_PROMPT)
    assert result.reason == "decisions: complex (1.00)"
    app, _ = await world(serve(answer("complex", probs(complex_=0.91), confidence=0.2)))
    assert (await classify(app, SHORT_PROMPT)).reason == "decisions: complex (0.91)"


@pytest.mark.parametrize("choice", [" Complex\n", "COMPLEX", "\tcomplex "])
async def test_choice_case_and_whitespace_are_ignored(world, choice):
    app, _ = await world(serve(answer(choice, {"complex": 0.9, "light": 0.1})))
    assert (await classify(app, SHORT_PROMPT)).tier == "complex"


async def test_probability_keys_are_matched_the_same_way(world):
    app, _ = await world(serve(answer("complex", {" Complex ": 0.4, "light": 0.3})))
    result = await classify(app, COMPLEX_PROMPT)  # 0.4 is weak; rules also say complex
    assert result.tier == "complex" and "weak" in result.reason


# --- the weak-answer rule ---------------------------------------------------------------------


async def test_a_weak_answer_below_the_rules_takes_the_rules_tier(world):
    app, _ = await world(serve(answer("light", probs(light=0.4, standard=0.35, complex_=0.25))))
    result = await classify(app, COMPLEX_PROMPT)
    assert (result.tier, result.classifier) == ("complex", "rules")
    assert "weak" in result.reason and "light 0.40" in result.reason
    assert result.signals  # the rules' signals ride along


async def test_a_weak_answer_the_same_as_the_rules_keeps_decisions(world):
    app, _ = await world(serve(answer("light", probs(light=0.4))))
    result = await classify(app, LIGHT_PROMPT)  # the rules say light too
    assert (result.tier, result.classifier) == ("light", "decisions")
    assert "weak" in result.reason


async def test_a_weak_answer_above_the_rules_keeps_decisions(world):
    app, _ = await world(serve(answer("complex", probs(complex_=0.4))))
    result = await classify(app, LIGHT_PROMPT)
    assert (result.tier, result.classifier) == ("complex", "decisions")


async def test_a_confident_answer_is_not_overridden_by_the_rules(world):
    app, _ = await world(serve(answer("light", probs(light=0.9))))
    result = await classify(app, COMPLEX_PROMPT)
    assert (result.tier, result.classifier) == ("light", "decisions")
    assert "weak" not in result.reason


async def test_exactly_half_is_trusted_alone(world):
    app, _ = await world(serve(answer("light", probs(light=0.5))))
    result = await classify(app, COMPLEX_PROMPT)
    assert (result.tier, result.classifier) == ("light", "decisions")


async def test_just_under_half_is_weak(world):
    app, _ = await world(serve(answer("light", probs(light=0.4999))))
    assert (await classify(app, COMPLEX_PROMPT)).tier == "complex"


async def test_the_confidence_is_used_when_there_is_no_probabilities_map(world):
    app, _ = await world(serve(answer("light", confidence=0.4)))
    assert (await classify(app, COMPLEX_PROMPT)).tier == "complex"
    app, _ = await world(serve(answer("light", confidence=0.9)))
    assert (await classify(app, COMPLEX_PROMPT)).tier == "light"


async def test_the_chosen_options_probability_wins_over_the_confidence(world):
    # the recorded lookup: probability 0.93 but confidence 0.90; build the opposite
    app, _ = await world(serve(answer("light", probs(light=0.9), confidence=0.1)))
    assert (await classify(app, COMPLEX_PROMPT)).tier == "light"
    app, _ = await world(serve(answer("light", probs(light=0.1), confidence=0.99)))
    assert (await classify(app, COMPLEX_PROMPT)).tier == "complex"


@pytest.mark.parametrize(
    "extra",
    [
        {"probabilities": {"standard": 0.9}},  # the chosen option is missing from the map
        {"probabilities": "high"},  # not a map
        {"probabilities": {"light": None}, "confidence": "high"},
        {"probabilities": {"light": float("nan")}, "confidence": None},
    ],
)
async def test_a_known_choice_with_unreadable_strength_is_trusted_alone(world, extra):
    body = answer("light")
    body["answers"]["tier"].update(extra)
    app, _ = await world(lambda request, n: httpx2.Response(200, content=json.dumps(body)))
    result = await classify(app, COMPLEX_PROMPT)
    assert (result.tier, result.classifier) == ("light", "decisions")
    assert result.reason == "decisions: light"


# --- failure falls back, never fatal ----------------------------------------------------------


@pytest.mark.parametrize(
    ("responder", "category"),
    [
        (serve({"error": {"message": "slow"}}, 429, {"Retry-After": "600"}), "rate_limited"),
        (serve({"error": {"message": "down"}}, 503), "upstream_failure"),
        (serve({"error": {"message": "no"}}, 403), "forbidden"),
        (serve({"error": {"message": "key"}}, 401), "authentication"),
        (serve({"error": {"message": "bad"}}, 400), "invalid_request"),
    ],
)
async def test_a_failed_request_falls_back_and_is_recorded_with_its_category(
    world, responder, category
):
    app, _ = await world(responder)
    result = await classify(app, COMPLEX_PROMPT)
    assert (result.tier, result.classifier) == ("complex", "rules")
    assert f"({category})" in result.reason and "rules:" in result.reason
    ((event,)) = await events(app)
    assert (event["status"], event["api"], event["tool"]) == (
        category,
        "decisions",
        "perplexity_ask",
    )


async def test_forbidden_falls_back_on_every_call(world):
    app, upstream = await world(serve({"error": {"message": "no"}}, 403))
    for _ in range(3):
        result = await classify(app, LIGHT_PROMPT)
        assert (result.tier, result.classifier) == ("light", "rules")
    assert upstream.calls == 3
    assert [e["status"] for e in await events(app)] == ["forbidden"] * 3


async def test_a_transport_error_falls_back(world):
    def boom(request, n):
        raise httpx2.ConnectError("no route", request=request)

    app, _ = await world(boom)
    result = await classify(app, LIGHT_PROMPT)
    assert result.classifier == "rules" and "(network_timeout)" in result.reason


async def test_an_unknown_choice_falls_back_with_no_failure_category(world):
    app, _ = await world(serve(answer("huge", probs(light=0.1))))
    result = await classify(app, COMPLEX_PROMPT)
    assert (result.tier, result.classifier) == ("complex", "rules")
    assert "unreadable" in result.reason
    assert not any(c in result.reason for c in ("rate_limited", "network_timeout", "failed"))
    assert [e["status"] for e in await events(app)] == ["ok"]  # the request itself was billed


@pytest.mark.parametrize(
    "body",
    [
        {"model": "m", "answers": {}, "usage": {"input_tokens": 5}},
        {"model": "m", "answers": {"tier": "stray"}, "usage": {"input_tokens": 5}},
        {"model": "m", "answers": {"tier": {"type": "score", "score": 1.0}}},
        {"model": "m", "answers": {"tier": {"type": "choice"}}},
        {"model": "m", "answers": {"tier": {"type": "choice", "choice": 7}}},
    ],
)
async def test_an_unreadable_answer_falls_back(world, body):
    app, _ = await world(serve(body))
    result = await classify(app, LIGHT_PROMPT)
    assert (result.tier, result.classifier) == ("light", "rules")
    assert "unreadable" in result.reason


async def test_a_prompt_that_is_an_image_makes_no_request(world):
    app, upstream = await world(serve(fixture("light")))
    result = await classify(app, "data:image/png;base64,AAAA")
    assert upstream.calls == 0 and await events(app) == []
    assert (result.tier, result.classifier) == ("standard", "rules")
    assert "not classifiable" in result.reason


async def test_a_blank_prompt_makes_no_request(world):
    app, upstream = await world(serve(fixture("light")))
    result = await classify(app, "   ")
    assert upstream.calls == 0 and "not classifiable" in result.reason


async def test_an_unexpected_error_falls_back(world, monkeypatch):
    async def explode(*args, **kwargs):
        raise RuntimeError("bug")

    app, _ = await world(serve(fixture("light")))
    monkeypatch.setattr(decisions, "run_decide", explode)
    result = await classify(app, LIGHT_PROMPT)
    assert result.classifier == "rules" and "(internal_error)" in result.reason


# --- the bound --------------------------------------------------------------------------------


async def test_a_request_past_the_bound_falls_back_and_records_one_timeout(world, monkeypatch):
    monkeypatch.setattr(routing_decisions, "BOUND_SECONDS", 0.05)

    async def slow(request, n):
        await asyncio.sleep(5)
        return httpx2.Response(200, json=fixture("light"))

    app, upstream = await world(slow)
    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await classify(app, COMPLEX_PROMPT)
    assert loop.time() - started < 2
    assert (result.tier, result.classifier) == ("complex", "rules")
    assert "(network_timeout)" in result.reason
    ((event,)) = await events(app)
    assert (event["status"], event["api"], event["tool"]) == (
        "network_timeout", "decisions", "perplexity_ask",
    )  # fmt: skip


async def test_a_rate_limit_is_reported_at_once_and_not_retried_into_a_timeout(world):
    # default retry settings: a 429 asking for a 2 second wait would be retried and the 3 second
    # bound would cut that sleep, reporting network_timeout; the classifier makes one attempt
    app, upstream = await world(
        serve({"error": {"message": "slow"}}, 429, {"Retry-After": "2"}), max_attempts=3
    )
    started = asyncio.get_running_loop().time()
    result = await classify(app, LIGHT_PROMPT)
    assert asyncio.get_running_loop().time() - started < 1.0
    assert upstream.calls == 1 and "(rate_limited)" in result.reason
    assert [e["status"] for e in await events(app)] == ["rate_limited"]


async def test_a_deadline_already_past_still_falls_back_and_records_the_timeout(world, monkeypatch):
    monkeypatch.setattr(routing_decisions, "BOUND_SECONDS", 0)

    async def slow(request, n):  # suspends, as a real connection does
        await asyncio.sleep(30)
        return httpx2.Response(200, json=fixture("light"))

    app, _ = await world(slow)
    result = await classify(app, LIGHT_PROMPT)
    assert result.classifier == "rules" and "network_timeout" in result.reason
    assert [e["status"] for e in await events(app)] == ["network_timeout"]


@pytest.mark.parametrize("strength", [7.0, -3.0])
async def test_a_strength_outside_zero_to_one_is_unreadable_and_trusts_the_answer(world, strength):
    body = answer("complex", {"light": 0.1, "standard": 0.1, "complex": strength}, confidence=None)
    app, _ = await world(serve(body))
    result = await classify(app, LIGHT_PROMPT)
    assert result.tier == "complex" and result.classifier == "decisions"
    assert not any(s in result.reason for s in ("nan", "7.00", "-3.00", "inf"))


@pytest.mark.parametrize("strength", [float("nan"), float("inf")])
async def test_a_non_finite_strength_never_reaches_the_reason(world, strength):
    body = answer("complex", {"light": 0.1, "standard": 0.1, "complex": strength})
    app, _ = await world(serve(body))
    result = await classify(app, LIGHT_PROMPT)  # trusted alone, or a fallback: never an error
    assert result.tier in ("light", "complex")
    assert not any(s in result.reason.lower() for s in ("nan", "inf"))


def test_the_criteria_cannot_be_changed_in_place():
    with pytest.raises(TypeError):
        CRITERIA["light"] = "x"  # type: ignore[index]


async def test_a_real_client_cancel_propagates_and_is_not_folded_into_the_fallback(world):
    async def slow(request, n):
        await asyncio.sleep(30)
        return httpx2.Response(200, json=fixture("light"))

    app, upstream = await world(slow)
    task = asyncio.create_task(classify(app, LIGHT_PROMPT))
    await asyncio.wait_for(upstream.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await events(app) == []  # cancelled before a response: nothing recorded


async def test_run_decide_without_a_deadline_is_unbounded_and_keeps_its_tool(world):
    app, _ = await world(serve(fixture("light")))
    costed = await decisions.run_decide(
        app, project="alpha", body=decisions.build_request(_options("hello"))
    )
    assert costed.status == "ok"
    ((event,)) = await events(app)
    assert event["tool"] == "perplexity_decide"  # the default is unchanged


def _options(state):
    return decisions.DecideOptions(
        state=state, questions={"tier": {"type": "choice", "criteria": dict(CRITERIA)}}
    )


# --- recording --------------------------------------------------------------------------------


async def test_one_event_with_the_callers_tool_api_project_and_computed_cost(world):
    app, _ = await world(serve(fixture("light")))
    await classify(app, LIGHT_PROMPT, tool="perplexity_chat", project="beta")
    ((event,)) = await events(app)
    assert (event["tool"], event["api"], event["status"], event["project_name"]) == (
        "perplexity_chat", "decisions", "ok", "beta",
    )  # fmt: skip
    assert (event["input_tokens"], event["cost_source"], event["cost_nano_usd"]) == (
        149, "computed", 149 * 20,
    )  # fmt: skip


# --- the prompt is written nowhere else -------------------------------------------------------


@pytest.mark.parametrize(
    "responder",
    [
        serve(answer("light", probs(light=0.9))),
        serve(answer("light", probs(light=0.4))),
        serve(answer("huge")),
        serve({"error": {"message": "echo hunter2 back"}}, 429, {"Retry-After": "600"}),
        serve({"error": {"message": "x"}}, 503),
    ],
)
async def test_the_prompt_is_not_in_the_reason_the_logs_or_the_event(world, responder, caplog):
    prompt = f"My password is {SECRET}. What is the latest Python? {SECRET}"
    app, _ = await world(responder)
    with caplog.at_level(logging.DEBUG):
        result = await classify(app, prompt)
    assert SECRET not in result.reason and SECRET not in "".join(result.signals)
    assert SECRET not in caplog.text
    assert SECRET not in json.dumps(await events(app), default=str)


async def test_a_refused_prompt_is_not_in_the_reason_either(world, caplog):
    with caplog.at_level(logging.DEBUG):
        app, _ = await world(serve(fixture("light")))
        result = await classify(app, f"data:image/png;base64,{SECRET}")
    assert SECRET not in result.reason and SECRET not in caplog.text


# --- the reason vocabulary --------------------------------------------------------------------


async def test_a_long_rules_reason_is_capped_at_120_ascii_characters(world, monkeypatch):
    long_reason = "é" * 200
    monkeypatch.setattr(
        rules, "classify", lambda text: rules.Classification("complex", long_reason, "rules", ())
    )
    for responder in (
        serve({"error": {"message": "slow"}}, 429, {"Retry-After": "600"}),
        serve(answer("huge")),
        serve(answer("light", probs(light=0.2))),
    ):
        app, _ = await world(responder)
        result = await classify(app, "anything at all?")
        assert len(result.reason) <= 120 and result.reason.isascii()
    result = await classify(app, "data:image/x")
    assert len(result.reason) <= 120 and result.reason.isascii()

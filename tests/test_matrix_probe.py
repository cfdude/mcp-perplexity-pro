"""model-matrix task 4.1: the effort probe (design D6) and its recording (usage-recording delta).

The upstream is a path-aware ``MockTransport`` (``matrix_support.Upstream``); the Agent bodies are
the recorded ``agent_fast.json`` with a fresh id (and, where a test needs a price, an edited
cost) and ``agent_empty_input_400.json`` for a refusal; edge cases (a failed run) are built inline.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from agent_support import fixture, inline
from matrix_support import MatrixWorld, Upstream, make_matrix_world, payload_with

from mcp_perplexity_pro import matrix, matrix_refresh
from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import PerplexityError

NOW = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)
LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"]
ORDER = [None, *LEVELS]  # the control, then the six levels
KEY = "test-dummy-api-key"
LOGGER = "mcp_perplexity_pro.matrix_refresh"
NEW = "acme/new-1"


# --- the fake agent -----------------------------------------------------------------------------


def completed(n: int, cost: float | None = None) -> httpx2.Response:
    body = fixture("agent_fast.json")
    body["id"] = f"resp_probe-{n}"
    if cost is not None:
        body["usage"]["cost"]["total_cost"] = cost
    return httpx2.Response(200, json=body)


def refusal() -> httpx2.Response:
    return httpx2.Response(400, json=fixture("agent_empty_input_400.json"))


def status(code: int) -> httpx2.Response:
    return httpx2.Response(code, json={"error": {"message": f"http {code}"}})


def level_of(body: dict) -> str | None:
    return (body.get("reasoning") or {}).get("effort")


class Agent:
    """Answers a probe request by ``(model, level)``: ``rules`` maps to a response or a callable
    ``(n) -> response``; a level with no rule is completed. ``cost`` prices every completion."""

    def __init__(self, rules=None, cost=None):
        self.rules = dict(rules or {})
        self.cost = cost

    def __call__(self, body, n):
        rule = self.rules.get((body["model"], level_of(body)))
        if rule is None:
            return completed(n, self.cost)
        return rule(n) if callable(rule) else rule


def refusing(model, *levels):
    return {(model, lv): refusal() for lv in levels}


# --- worlds -------------------------------------------------------------------------------------


@pytest.fixture
async def worlds(make_settings):
    made: list[MatrixWorld] = []

    async def factory(upstream: Upstream, **kwargs) -> MatrixWorld:
        kwargs.setdefault("refresh_task", False)
        kwargs.setdefault("matrix_refresh", 0)
        world = await make_matrix_world(make_settings, upstream, **kwargs)
        world.app.matrix.now = lambda: NOW
        made.append(world)
        return world

    yield factory
    for world in made:
        await world.aclose()


def path_of(world: MatrixWorld) -> Path:
    return world.settings.data_dir / matrix.FILENAME


def stored(world: MatrixWorld) -> matrix.Matrix:
    loaded = matrix.load(path_of(world))
    assert loaded.state == "ok"
    return loaded.matrix


def entry(world: MatrixWorld, model_id: str) -> matrix.ModelEntry:
    return stored(world).models[model_id]


def stamp(moment: datetime) -> str:
    return matrix.stamp(moment)


async def refresh(world: MatrixWorld) -> None:
    await matrix_refresh.run_refresh(world.app)  # interval 0: one refresh, then it returns


async def seed(world: MatrixWorld, *ids: str, **fields) -> None:
    """Store the baseline plus ``ids`` as available, unprobed models (``fields`` on each row)."""

    def add(current: matrix.Matrix) -> matrix.Matrix:
        copy = current.model_copy(deep=True)
        for model_id in ids:
            values = {
                "provider": "acme",
                "status": "available",
                "pricing": matrix.Pricing(input=1.0, output=1.0),
                "first_seen": stamp(NOW),
                "last_seen": stamp(NOW),
                **fields,
            }
            copy.models[model_id] = matrix.ModelEntry(**values)
        return copy

    result = await matrix.update(world.settings.data_dir, add, now=NOW)
    assert result.status == "written"


def requests_of(world: MatrixWorld) -> list[tuple[str, str | None]]:
    return [(b["model"], level_of(b)) for b in world.upstream.agent_bodies]


# --- PerplexityClient.probe_effort --------------------------------------------------------------


def client_over(make_settings, handler, **kwargs) -> PerplexityClient:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))

    async def no_sleep(_seconds):
        raise AssertionError("the probe slept before a retry")

    return PerplexityClient(make_settings(**kwargs), http=http, sleep=no_sleep)


async def test_probe_effort_sends_the_exact_body_with_the_effort():
    seen = []

    def handler(request):
        seen.append(request)
        return completed(1)

    from mcp_perplexity_pro.settings import Settings

    client = PerplexityClient(
        Settings(api_key=KEY),
        http=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    run = await client.probe_effort("acme/x", "xhigh")
    assert run.status == "completed"
    (request,) = seen
    assert request.method == "POST" and request.url.path == "/v1/agent"
    assert json.loads(request.content) == {
        "model": "acme/x",
        "input": "Reply with the single word OK.",
        "store": False,
        "max_output_tokens": 300,
        "reasoning": {"effort": "xhigh"},
    }
    timeout = request.extensions["timeout"]
    assert timeout["read"] == 30 and timeout["connect"] == 30  # one 30 s limit


async def test_probe_effort_for_the_control_sends_no_reasoning_at_all(make_settings):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return completed(1)

    client = client_over(make_settings, handler)
    await client.probe_effort("acme/x", None)
    assert "reasoning" not in seen[0] and seen[0]["model"] == "acme/x"


async def test_probe_effort_makes_one_attempt_even_on_a_429(make_settings):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(429, json={"error": {"message": "slow down"}})

    client = client_over(make_settings, handler, max_attempts=3)
    with pytest.raises(PerplexityError) as caught:
        await client.probe_effort("acme/x", "low")
    assert caught.value.status == 429 and len(seen) == 1  # no retry, no sleep


# --- what a probe records for a new model -------------------------------------------------------


async def test_a_new_model_is_probed_control_first_then_each_level_in_order(worlds, caplog):
    world = await worlds(Upstream(models=payload_with(NEW), agent=Agent()))
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await refresh(world)
    assert requests_of(world) == [(NEW, level) for level in ORDER]
    assert "reasoning" not in world.upstream.agent_bodies[0]  # the control carries no effort
    row = entry(world, NEW)
    assert row.efforts.source == "probe" and row.efforts.accepted == LEVELS
    assert row.efforts.refused == {} and row.efforts.probed_at == stamp(NOW)
    assert row.efforts.answers == {"control": 200, **{lv: 200 for lv in LEVELS}}
    assert row.probing_until is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_the_recorded_baseline_models_and_a_fresh_install_probe_nothing(worlds):
    world = await worlds(Upstream(agent=Agent()))  # the live list is the baseline's own 54
    await refresh(world)
    assert world.upstream.agent_bodies == []
    sources = {e.efforts.source for e in stored(world).models.values()}
    assert sources == {"baseline"}


async def test_a_model_that_refuses_xhigh_and_max_is_stored_with_the_four_it_accepts(worlds):
    agent = Agent(refusing(NEW, "xhigh", "max"))
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    row = entry(world, NEW).efforts
    assert row.source == "probe"
    assert row.accepted == ["minimal", "low", "medium", "high"]
    assert row.refused == {"xhigh": 400, "max": 400}
    assert row.answers["xhigh"] == 400 and row.answers["control"] == 200


async def test_a_model_that_refuses_all_six_levels_with_a_good_control_is_probed(worlds):
    agent = Agent(refusing(NEW, *LEVELS))
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    row = entry(world, NEW).efforts
    assert row.source == "probe" and row.accepted == []
    assert row.refused == {lv: 400 for lv in LEVELS}


@pytest.mark.parametrize(
    "control",
    [
        pytest.param(refusal(), id="400"),
        pytest.param(status(500), id="500"),
        pytest.param(status(503), id="503"),
        pytest.param(httpx2.Response(200, json=inline("failed")), id="failed-run"),
        pytest.param(httpx2.Response(200, json=inline("incomplete")), id="incomplete-run"),
    ],
)
async def test_a_broken_control_records_no_refusal_and_sends_no_level(worlds, control):
    agent = Agent({(NEW, None): control})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    assert requests_of(world) == [(NEW, None)]  # without a good control a 400 means nothing
    row = entry(world, NEW)
    assert row.efforts.source == "unprobed" and row.efforts.answers == {}
    assert row.efforts.refused == {} and row.probing_until is None


# --- partial answers, 429, a run that did not complete ------------------------------------------


async def test_a_429_ends_the_round_keeps_the_answers_and_the_next_refresh_sends_the_rest(worlds):
    other = "acme/new-2"
    agent = Agent({(NEW, "high"): status(429)})
    world = await worlds(Upstream(models=payload_with(NEW, other), agent=agent))
    await refresh(world)
    assert requests_of(world) == [(NEW, lv) for lv in ORDER[:5]]  # ends at the 429: no 2nd model
    row = entry(world, NEW)
    assert row.efforts.source == "unprobed" and row.efforts.accepted == []
    assert row.efforts.answers == {"control": 200, "minimal": 200, "low": 200, "medium": 200}
    assert row.probing_until is None
    assert entry(world, other).efforts.answers == {}  # never started
    agent.rules.clear()  # the limit passes
    world.upstream.agent_bodies.clear()
    await refresh(world)
    assert requests_of(world)[:3] == [(NEW, "high"), (NEW, "xhigh"), (NEW, "max")]
    assert (NEW, None) not in requests_of(world)  # the control is not asked again
    done = entry(world, NEW).efforts
    assert done.source == "probe" and done.accepted == LEVELS


async def test_a_429_is_never_counted_as_a_refusal(worlds):
    agent = Agent({(NEW, "low"): status(429)})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    answers = entry(world, NEW).efforts.answers
    assert "low" not in answers and 400 not in answers.values()


@pytest.mark.parametrize(
    "unfinished",
    [
        pytest.param(httpx2.Response(200, json=inline("failed")), id="failed"),
        pytest.param(httpx2.Response(200, json=inline("incomplete")), id="incomplete"),
        pytest.param(httpx2.Response(200, json=inline("queued")), id="queued"),
        pytest.param(httpx2.Response(200, json=inline("in_progress")), id="in_progress"),
        pytest.param(status(500), id="500"),
        pytest.param(status(502), id="502"),
    ],
)
async def test_a_level_that_did_not_complete_is_unanswered_not_accepted_or_refused(
    worlds, unfinished
):
    agent = Agent({(NEW, "low"): unfinished})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    assert [lv for _m, lv in requests_of(world)] == ORDER  # the other levels were still asked
    row = entry(world, NEW).efforts
    assert row.source == "unprobed" and "low" not in row.answers
    assert row.answers == {k: 200 for k in ["control", "minimal", "medium", "high", "xhigh", "max"]}
    agent.rules.clear()
    world.upstream.agent_bodies.clear()
    await refresh(world)
    assert requests_of(world) == [(NEW, "low")]  # only the unanswered level
    assert entry(world, NEW).efforts.source == "probe"


async def test_a_timeout_leaves_that_level_unanswered(worlds):
    def timed_out(_n):
        raise httpx2.ReadTimeout("slow")

    agent = Agent({(NEW, "medium"): timed_out})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    row = entry(world, NEW).efforts
    assert row.source == "unprobed" and "medium" not in row.answers and "high" in row.answers


# --- the bounds ---------------------------------------------------------------------------------


async def test_fourteen_unprobed_models_give_ten_probed_and_seventy_requests(worlds):
    ids = [f"acme/m{i:02d}" for i in range(14)]
    world = await worlds(Upstream(models=payload_with(*ids), agent=Agent()))
    await refresh(world)
    assert len(world.upstream.agent_bodies) == 70
    sources = [entry(world, i).efforts.source for i in ids]
    assert sources.count("probe") == 10 and sources.count("unprobed") == 4
    world.upstream.agent_bodies.clear()
    await refresh(world)  # the other four wait for the next refresh
    assert len(world.upstream.agent_bodies) == 28
    assert {entry(world, i).efforts.source for i in ids} == {"probe"}


async def test_the_spend_cap_is_checked_before_each_model(worlds):
    ids = [f"acme/m{i:02d}" for i in range(6)]
    # 7 requests at $0.0125 each = $0.0875 a model; $0.25 is reached after the third model
    world = await worlds(Upstream(models=payload_with(*ids), agent=Agent(cost=0.0125)))
    await refresh(world)
    assert len(world.upstream.agent_bodies) == 21  # three models; the fourth never starts
    sources = [entry(world, i).efforts.source for i in ids]
    assert sources == ["probe"] * 3 + ["unprobed"] * 3


async def test_a_model_just_under_the_cap_is_still_followed_by_the_next(worlds):
    ids = [f"acme/m{i:02d}" for i in range(4)]
    world = await worlds(Upstream(models=payload_with(*ids), agent=Agent(cost=0.001)))
    await refresh(world)  # 4 x 7 x $0.001 = $0.028: far under the cap
    assert len(world.upstream.agent_bodies) == 28


async def test_probing_off_makes_no_request_and_leaves_new_models_unprobed(worlds):
    world = await worlds(Upstream(models=payload_with(NEW), agent=Agent()), matrix_probe="off")
    await refresh(world)
    assert world.upstream.agent_bodies == []
    row = entry(world, NEW)
    assert row.efforts.source == "unprobed" and row.probing_until is None


# --- leases -------------------------------------------------------------------------------------


async def test_the_lease_is_written_before_the_probe_and_the_lock_is_free_during_it(worlds):
    reached, release = asyncio.Event(), asyncio.Event()

    async def held(_n):
        reached.set()
        await release.wait()
        return completed(99)

    agent = Agent({(NEW, "low"): held})
    world = await worlds(Upstream(agent=agent))
    await seed(world, NEW)
    probe = asyncio.create_task(matrix_refresh.probe_new(world.app))
    await asyncio.wait_for(reached.wait(), 10)
    row = entry(world, NEW)  # read while the request is in flight
    assert row.probing_until == stamp(NOW + timedelta(minutes=10))
    # the lock is never held across a request: another writer gets in at once
    result = await matrix.update(world.settings.data_dir, lambda m: None, timeout=1.0)
    assert result.status == "unchanged"
    release.set()
    await probe
    done = entry(world, NEW)
    assert done.probing_until is None and done.efforts.source == "probe"


async def test_a_model_leased_by_another_server_is_not_probed(worlds):
    world = await worlds(Upstream(agent=Agent()))
    soon = stamp(NOW + timedelta(minutes=5))
    await seed(world, NEW, probing_until=soon)
    await matrix_refresh.probe_new(world.app)
    assert world.upstream.agent_bodies == []
    assert entry(world, NEW).probing_until == soon  # their lease is untouched


async def test_an_expired_lease_does_not_stop_a_probe(worlds):
    world = await worlds(Upstream(agent=Agent()))
    await seed(world, NEW, probing_until=stamp(NOW - timedelta(seconds=1)))
    await matrix_refresh.probe_new(world.app)
    assert len(world.upstream.agent_bodies) == 7 and entry(world, NEW).probing_until is None


async def test_a_model_probed_elsewhere_after_the_read_is_not_probed(worlds, monkeypatch):
    world = await worlds(Upstream(agent=Agent()))
    await seed(world, NEW)
    real = matrix_refresh._take_lease

    async def raced(app, model_id):
        def other_server_finishes(current):
            copy = current.model_copy(deep=True)
            efforts = copy.models[model_id].efforts
            efforts.source, efforts.accepted, efforts.probed_at = "probe", list(LEVELS), "x"
            return copy

        await matrix.update(app.settings.data_dir, other_server_finishes, now=NOW)
        return await real(app, model_id)

    monkeypatch.setattr(matrix_refresh, "_take_lease", raced)
    await matrix_refresh.probe_new(world.app)
    assert world.upstream.agent_bodies == []  # re-read under the lock: nothing left to probe
    assert entry(world, NEW).efforts.accepted == LEVELS


async def test_a_cancel_mid_model_keeps_the_answered_levels_and_clears_the_lease(worlds):
    reached = asyncio.Event()

    async def held(_n):
        reached.set()
        await asyncio.sleep(60)

    agent = Agent({(NEW, "medium"): held})
    world = await worlds(Upstream(agent=agent))
    await seed(world, NEW)
    probe = asyncio.create_task(matrix_refresh.probe_new(world.app))
    await asyncio.wait_for(reached.wait(), 10)
    probe.cancel()
    with pytest.raises(asyncio.CancelledError):
        await probe
    row = entry(world, NEW)
    assert row.efforts.answers == {"control": 200, "minimal": 200, "low": 200}
    assert row.probing_until is None and row.efforts.source == "unprobed"
    agent.rules.clear()
    world.upstream.agent_bodies.clear()
    await matrix_refresh.probe_new(world.app)
    assert [lv for _m, lv in requests_of(world)] == ["medium", "high", "xhigh", "max"]
    assert entry(world, NEW).efforts.source == "probe"


async def test_an_unexpected_error_clears_the_lease_and_warns_once(worlds, caplog):
    def explode(_n):
        raise RuntimeError(f"boom (key {KEY})")

    agent = Agent({(NEW, "low"): explode})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await refresh(world)  # the task still returns
    row = entry(world, NEW)
    assert row.probing_until is None and row.efforts.answers == {"control": 200, "minimal": 200}
    warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warned) == 1 and KEY not in warned[0].getMessage()


async def test_removed_models_are_not_probed(worlds):
    world = await worlds(Upstream(agent=Agent()))
    await seed(world, NEW, status="removed")
    await matrix_refresh.probe_new(world.app)
    assert world.upstream.agent_bodies == []


# --- recording ----------------------------------------------------------------------------------


async def test_every_probe_request_is_one_event_under_model_matrix_with_no_project(worlds):
    agent = Agent(
        {
            (NEW, "minimal"): refusal(),
            (NEW, "low"): httpx2.Response(200, json=inline("failed")),
            (NEW, "medium"): status(500),
            (NEW, "high"): status(429),
        }
    )
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    rows = await world.rows(
        "SELECT tool, api, status, project_id, project_name FROM usage_events ORDER BY id"
    )
    assert rows == [
        ("model_matrix", "agent", "ok", None, None),  # the control
        ("model_matrix", "agent", "invalid_request", None, None),  # minimal: 400
        ("model_matrix", "agent", "unexpected_response", None, None),  # low: a failed run
        ("model_matrix", "agent", "upstream_failure", None, None),  # medium: 500
        ("model_matrix", "agent", "rate_limited", None, None),  # high: 429 ends the round
    ]
    assert await world.rows("SELECT count(*) FROM projects") == [(0,)]


async def test_a_queued_response_has_no_terminal_state_and_is_not_recorded(worlds):
    agent = Agent({(NEW, "low"): httpx2.Response(200, json=inline("queued"))})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    assert len(world.upstream.agent_bodies) == 7
    assert await world.rows("SELECT count(*) FROM usage_events") == [(6,)]


async def test_seventy_events_are_recorded_for_ten_models_and_usage_groups_them_under_none(
    worlds,
):
    from fastmcp import Client

    ids = [f"acme/m{i:02d}" for i in range(10)]
    world = await worlds(Upstream(models=payload_with(*ids), agent=Agent(cost=0.001)))
    await refresh(world)
    assert await world.rows("SELECT count(*), sum(cost_nano_usd) FROM usage_events") == [
        (70, 70 * 1_000_000)
    ]
    async with Client(world.server) as client:
        result = await client.call_tool("perplexity_usage", {"group_by": "project"})
    groups = result.structured_content["groups"]
    assert [g["key"] for g in groups] == ["(none)"] and groups[0]["calls"] == 70

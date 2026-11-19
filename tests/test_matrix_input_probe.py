"""media-inputs task 2.2: the input probe (design D6): `client.probe_input`, per-kind selection,
the same-round control, answers by HTTP status, per-kind backoff and the stale-refusal re-probe.

Uses the helpers of the effort-probe tests; the input probe is NOT switched off here."""

import json
from datetime import timedelta

import httpx2
import media_support as ms
import pytest
from agent_support import inline
from matrix_support import (
    ADDED_AFTER_THE_SWEEP,
    MatrixWorld,
    Upstream,
    make_matrix_world,
    payload_with,
)
from test_matrix_probe import (
    KEY,
    NOW,
    completed,
    entry,
    path_of,
    refresh,
    seed,
    stamp,
    status,
    stored,
)

from mcp_perplexity_pro import matrix, matrix_refresh
from mcp_perplexity_pro.client import PerplexityClient
from mcp_perplexity_pro.errors import PerplexityError

NEW = "acme/new-1"


async def silence_baseline(world: MatrixWorld, only: set[str] | None = None) -> None:
    """The baseline leaves about ten models with an unknown or a stale-refused kind; they would
    take the ten probe slots of a refresh before the model under test. Give each such kind a
    ``retry_after`` far ahead (a stored backoff), so only the models a test adds are probed.
    Tests about the baseline's own models pass ``quiet=False``; ``only`` silences just the named
    ids (the entry added by hand after the sweep has unanswered inputs and would take a slot)."""
    later = stamp(NOW + timedelta(days=30))

    def quiet(current: matrix.Matrix) -> matrix.Matrix:
        copy = current.model_copy(deep=True)
        for model_id, row in copy.models.items():
            if only is not None and model_id not in only:
                continue
            for kind in matrix_refresh._wants_inputs(row, row, NOW):
                row.inputs.retry_after[kind] = later
        return copy

    assert (await matrix.update(world.settings.data_dir, quiet, now=NOW)).status == "written"


@pytest.fixture
async def worlds(make_settings):
    made: list[MatrixWorld] = []

    async def factory(upstream: Upstream, *, quiet: bool = True, **kwargs) -> MatrixWorld:
        kwargs.setdefault("refresh_task", False)
        kwargs.setdefault("matrix_refresh", 0)
        world = await make_matrix_world(make_settings, upstream, **kwargs)
        world.app.matrix.now = lambda: NOW
        made.append(world)
        if quiet:
            await silence_baseline(world)
        return world

    yield factory
    for world in made:
        await world.aclose()


NAMED = "the selected model route does not support this document type or source"
GONE = 'validation failed: model "acme/new-1" is not supported'


def part_kind(body):
    """``image`` or ``document`` for an input probe body, else None (a control or an effort)."""
    items = body.get("input")
    if not isinstance(items, list):
        return None
    for part in items[0]["content"]:
        if part["type"] == "input_image":
            return "image"
        if part["type"] == "input_file":
            return "document"
    return None


def key_of(body):
    kind = part_kind(body)
    if kind:
        return kind
    return (body.get("reasoning") or {}).get("effort") or "control"


def failed_run(n):
    return httpx2.Response(200, json=inline("failed", error={"code": "refusal", "message": "x"}))


def bad(message):
    return httpx2.Response(
        400, json={"error": {"message": message, "type": "invalid_request", "code": 400}}
    )


class Agent:
    """Answers by ``(model, key)`` where key is ``control``, a level, ``image`` or ``document``;
    no rule is a completed run."""

    def __init__(self, rules=None, cost=None):
        self.rules = dict(rules or {})
        self.cost = cost

    def __call__(self, body, n):
        rule = self.rules.get((body["model"], key_of(body)))
        if rule is None:
            return completed(n, self.cost)
        return rule(n) if callable(rule) else rule


def asked(world, model, *, inputs_only=False):
    keys = [key_of(b) for b in world.upstream.agent_bodies if b["model"] == model]
    return [k for k in keys if k in ("image", "document")] if inputs_only else keys


def known(world, model):
    return entry(world, model).inputs


EFFORTS_KNOWN = dict(
    efforts=matrix.Efforts(accepted=["low"], source="probe", probed_at="2026-10-01T00:00:00Z")
)


async def only(world_factory, model, agent, *, inputs, **seed_fields):
    """A world where one extra model is stored with efforts known and the given inputs; the
    baseline's other models are given known inputs so only ``model`` is probed."""
    world = await world_factory(Upstream(models=payload_with(model), agent=agent))
    await seed(world, model, **EFFORTS_KNOWN, inputs=inputs, **seed_fields)
    return world


# --- the client ----------------------------------------------------------------------------


async def test_probe_input_sends_the_exact_body_for_each_kind():
    from mcp_perplexity_pro.settings import Settings

    seen = []

    def handler(request):
        seen.append(request)
        return completed(1)

    client = PerplexityClient(
        Settings(api_key=KEY),
        http=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    await client.probe_input("acme/x", "image")
    await client.probe_input("acme/x", "document")
    image, document = (json.loads(r.content) for r in seen)
    for body in (image, document):
        assert body["model"] == "acme/x" and body["store"] is False
        assert body["max_output_tokens"] == 150 and "tools" not in body
        (message,) = body["input"]
        assert message["type"] == "message" and message["role"] == "user"
        assert message["content"][0]["type"] == "input_text"
        assert len(message["content"]) == 2
    png = image["input"][0]["content"][1]
    assert png["type"] == "input_image"
    assert png["image_url"] == "data:image/png;base64," + ms.b64(ms.png())
    doc = document["input"][0]["content"][1]
    assert doc == {"type": "input_file", "filename": "doc.pdf", "file_data": ms.b64(ms.pdf())}
    request = seen[0]
    assert request.extensions["timeout"]["read"] == 30


async def test_probe_input_makes_one_attempt_even_on_a_429(make_settings):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(429, json={"error": {"message": "slow down"}})

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))

    async def no_sleep(_s):
        raise AssertionError("slept")

    client = PerplexityClient(make_settings(max_attempts=3), http=http, sleep=no_sleep)
    with pytest.raises(PerplexityError) as caught:
        await client.probe_input("acme/x", "document")
    assert caught.value.status == 429 and len(seen) == 1


async def test_probe_input_rejects_a_bad_kind(make_settings):
    client = PerplexityClient(make_settings(), http=httpx2.AsyncClient())
    with pytest.raises(ValueError):
        await client.probe_input("acme/x", "audio")


# --- eligibility ---------------------------------------------------------------------------


async def test_baseline_answers_count_so_a_fully_answered_model_is_not_probed(worlds):
    world = await worlds(Upstream(agent=Agent()), quiet=False)
    await refresh(world)
    assert asked(world, "openai/gpt-6-luna") == []  # both kinds answered by the baseline
    assert asked(world, "anthropic/claude-opus-5") == ["control", "document"]  # one unknown


async def test_a_model_with_one_unknown_kind_sends_only_that_kind_after_the_control(worlds):
    world = await worlds(Upstream(agent=Agent()), quiet=False)
    await refresh(world)
    row = known(world, "anthropic/claude-opus-5")
    assert row.accepted == ["image", "document"] and row.source == "probe"
    assert asked(world, "anthropic/claude-opus-5") == ["control", "document"]
    assert row.attempts == {"document": 1} and row.probed_at["image"].startswith("2026-10-30")


async def test_a_refused_kind_in_backoff_is_not_selected(worlds):
    inputs = matrix.Inputs(
        accepted=["image"],
        refused={"document": 400},
        probed_at={"image": stamp(NOW), "document": stamp(NOW - timedelta(days=2))},
        retry_after={"document": stamp(NOW + timedelta(days=5))},
        source="probe",
    )
    world = await only(worlds, NEW, Agent(), inputs=inputs)
    await refresh(world)
    assert asked(world, NEW) == []


async def test_a_recent_unanswered_attempt_counts_as_probed(worlds):
    inputs = matrix.Inputs(
        accepted=["image"],
        probed_at={"image": stamp(NOW)},
        last_attempt_at={"document": stamp(NOW - timedelta(minutes=1))},
        attempts={"document": 1},
        source="probe",
    )
    world = await only(worlds, NEW, Agent(), inputs=inputs)
    await refresh(world)
    assert asked(world, NEW) == []
    # ten minutes later the window has passed
    inputs_old = inputs.model_copy(
        update={"last_attempt_at": {"document": stamp(NOW - timedelta(minutes=11))}}
    )
    world2 = await only(worlds, NEW, Agent(), inputs=inputs_old)
    await refresh(world2)
    assert asked(world2, NEW) == ["control", "document"]


async def test_a_refused_merge_still_consults_the_baseline_per_kind(worlds):
    # a truncated live list: the merge changes nothing, yet a stored entry that has not attempted
    # a kind the baseline answers is not selected for it
    truncated = payload_with()
    truncated["data"] = truncated["data"][:5]
    world = await worlds(Upstream(models=truncated, agent=Agent()))
    old = matrix.load_baseline().model_copy(deep=True)
    for e in old.models.values():
        e.inputs = matrix.Inputs()  # as stored before this change

    await_write = matrix.update(world.settings.data_dir, lambda current: old, now=NOW)
    assert (await await_write).status == "written"
    await refresh(world)
    assert asked(world, "openai/gpt-6-luna") == []
    assert asked(world, "anthropic/claude-opus-5") == ["control", "document"]


# --- the same-round control ----------------------------------------------------------------


async def test_a_new_model_shares_one_control_between_efforts_and_inputs(worlds):
    world = await worlds(Upstream(models=payload_with(NEW), agent=Agent()))
    await refresh(world)
    keys = asked(world, NEW)
    assert keys == [
        "control",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "image",
        "document",
    ]
    row = known(world, NEW)
    assert row.accepted == ["image", "document"] and row.source == "probe"
    assert entry(world, NEW).efforts.source == "probe"


async def test_a_control_that_stopped_completing_records_no_kind_refused(worlds):
    agent = Agent({("anthropic/claude-opus-5", "control"): bad("invalid request")})
    world = await worlds(Upstream(agent=agent), quiet=False)
    await refresh(world)
    assert asked(world, "anthropic/claude-opus-5") == ["control"]  # no kind request was sent
    row = known(world, "anthropic/claude-opus-5")
    assert "document" not in row.refused and "document" not in row.accepted
    assert row.unanswered_rounds == {"document": 1}


async def test_a_stored_control_from_an_earlier_refresh_is_not_reused_for_inputs(worlds):
    efforts = matrix.Efforts(
        accepted=[], answers={"control": 200}, source="unprobed"
    )  # a partial effort probe from before: its control was answered in an earlier refresh
    world = await worlds(Upstream(models=payload_with(NEW), agent=Agent()))
    await seed(world, NEW, efforts=efforts)
    await refresh(world)
    keys = asked(world, NEW)
    assert keys[0] == "control" and keys.count("control") == 1  # a fresh one was sent
    assert keys[-2:] == ["image", "document"]


# --- the request and the answers -----------------------------------------------------------


async def test_the_input_request_has_one_part_and_no_tools(worlds):
    world = await worlds(Upstream(agent=Agent()), quiet=False)
    await refresh(world)
    bodies = [b for b in world.upstream.agent_bodies if part_kind(b) == "document"]
    assert bodies and all(b["store"] is False and b["max_output_tokens"] == 150 for b in bodies)
    assert all("tools" not in b for b in bodies)


async def test_a_generic_400_leaves_the_kind_unanswered_and_the_other_accepted(worlds):
    agent = Agent({(NEW, "image"): bad("invalid request")})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    row = known(world, NEW)
    assert row.accepted == ["document"] and "image" not in row.refused
    assert row.source == "probe" and row.unanswered_rounds == {"image": 1}
    assert row.attempts == {"image": 1, "document": 1}


async def test_a_named_refusal_is_refused_with_its_status(worlds):
    agent = Agent({(NEW, "document"): bad(NAMED)})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    row = known(world, NEW)
    assert row.refused == {"document": 400} and row.accepted == ["image"]
    assert row.source == "probe" and row.answers["document"] == 400


async def test_a_not_served_400_is_never_a_refusal(worlds):
    agent = Agent({(NEW, "image"): bad(GONE), (NEW, "document"): bad(GONE)})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    row = known(world, NEW)
    assert not row.accepted and not row.refused


async def test_a_429_is_never_a_refusal_and_stops_the_refresh(worlds):
    agent = Agent({(NEW, "image"): status(429)})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    keys = asked(world, NEW)
    assert keys[-1] == "image" and "document" not in keys  # the document was never sent
    row = known(world, NEW)
    assert not row.refused and "image" not in row.accepted
    # every other model waits for the next refresh
    assert [k for b in world.upstream.agent_bodies for k in [key_of(b)]].count("image") == 1


async def test_an_incomplete_run_is_accepted_and_recorded_unexpected_response(worlds):
    agent = Agent({(NEW, "image"): httpx2.Response(200, json=inline("incomplete"))})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    assert "image" in known(world, NEW).accepted
    rows = await world.rows("SELECT status FROM usage_events WHERE model = :m ORDER BY id", m=NEW)
    assert ("unexpected_response",) in rows


async def test_a_failed_run_leaves_the_kind_unanswered(worlds):
    agent = Agent({("anthropic/claude-opus-5", "document"): failed_run})
    world = await worlds(Upstream(agent=agent), quiet=False)
    await refresh(world)
    row = known(world, "anthropic/claude-opus-5")
    assert "document" not in row.accepted and "document" not in row.refused
    assert row.unanswered_rounds == {"document": 1}


async def test_a_5xx_and_a_timeout_leave_the_kind_unanswered(worlds):
    def boom(n):
        raise httpx2.ReadTimeout("slow")

    agent = Agent({(NEW, "image"): status(503), (NEW, "document"): boom})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    row = known(world, NEW)
    assert not row.accepted and not row.refused
    assert row.unanswered_rounds == {"image": 1, "document": 1}


# --- independent bookkeeping ---------------------------------------------------------------


async def test_an_effort_round_that_fails_does_not_mark_inputs_failed(worlds):
    agent = Agent({(NEW, "high"): status(503)})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    state = world.app.matrix
    assert NEW in state.failed_models and NEW not in state.input_failed_models
    assert known(world, NEW).accepted == ["image", "document"]  # the inputs are written as known
    assert entry(world, NEW).efforts.source == "unprobed"  # the efforts stay incomplete


async def test_an_input_round_that_fails_does_not_mark_efforts_failed(worlds):
    agent = Agent({(NEW, "image"): status(503)})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    state = world.app.matrix
    assert NEW in state.input_failed_models and NEW not in state.failed_models
    assert entry(world, NEW).efforts.source == "probe"


# --- recorded and bounded ------------------------------------------------------------------


async def test_input_probes_are_usage_events_of_model_matrix_with_no_project(worlds):
    world = await worlds(Upstream(models=payload_with(NEW), agent=Agent(cost=0.002)))
    await refresh(world)
    rows = await world.rows(
        "SELECT tool, api, project_id, cost_nano_usd FROM usage_events WHERE tool = 'model_matrix'"
    )
    assert len(rows) == 9 and {r[0] for r in rows} == {"model_matrix"}
    assert all(r[2] is None for r in rows) and all(r[3] == 2_000_000 for r in rows)
    assert await world.rows("SELECT count(*) FROM projects") == [(0,)]


async def test_ten_models_and_the_cost_cap_count_across_both_probes(worlds):
    ids = [f"acme/m{i:02d}" for i in range(12)]
    world = await worlds(Upstream(models=payload_with(*ids), agent=Agent(cost=0.001)))
    await refresh(world)
    probed = {b["model"] for b in world.upstream.agent_bodies}
    assert len(probed) == matrix_refresh.PROBE_MODELS_PER_REFRESH

    world2 = await worlds(Upstream(models=payload_with("acme/a", "acme/b"), agent=Agent(cost=0.2)))
    await refresh(world2)  # the first model's nine requests reach $0.25: no second model starts
    assert len({b["model"] for b in world2.upstream.agent_bodies}) == 1


# --- backoff per kind ----------------------------------------------------------------------


async def test_a_model_that_always_fails_a_kind_backs_off_after_two_rounds(worlds):
    model = "anthropic/claude-opus-5"
    agent = Agent({(model, "document"): failed_run})
    world = await worlds(Upstream(agent=agent), quiet=False)
    await refresh(world)
    assert known(world, model).unanswered_rounds == {"document": 1}
    world.app.matrix.now = lambda: NOW + timedelta(hours=1)
    world.upstream.agent_bodies.clear()
    await refresh(world)
    row = known(world, model)
    assert row.retry_after["document"] == stamp(NOW + timedelta(hours=1) + timedelta(days=7))
    assert row.unanswered_rounds.get("document", 0) == 0 and row.attempts["document"] == 2
    world.app.matrix.now = lambda: NOW + timedelta(hours=2)
    world.upstream.agent_bodies.clear()
    await refresh(world)
    assert asked(world, model) == []  # the third refresh sends no document probe


async def test_one_kind_answering_does_not_reset_the_other_kinds_count(worlds):
    agent = Agent({(NEW, "document"): failed_run})
    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    await refresh(world)
    world.app.matrix.now = lambda: NOW + timedelta(hours=1)
    await refresh(world)
    row = known(world, NEW)
    assert "document" in row.retry_after and row.accepted == ["image"]
    assert row.retry_after.get("image") is None


async def test_only_an_answer_for_the_kind_resets_its_count_and_backoff(worlds):
    inputs = matrix.Inputs(
        accepted=["image"],
        probed_at={"image": stamp(NOW)},
        unanswered_rounds={"document": 1},
        attempts={"document": 1},
        last_attempt_at={"document": stamp(NOW - timedelta(hours=2))},
        source="probe",
    )
    world = await only(worlds, NEW, Agent(), inputs=inputs)
    await refresh(world)
    row = known(world, NEW)
    assert row.accepted == ["image", "document"]
    assert "document" not in row.unanswered_rounds and "document" not in row.retry_after
    assert row.attempts == {"document": 2}  # attempts never resets


# --- a refusal is not permanent ------------------------------------------------------------


def refused_inputs(age: timedelta) -> matrix.Inputs:
    return matrix.Inputs(
        accepted=["image"],
        refused={"document": 400},
        answers={"image": 200, "document": 400},
        probed_at={"image": stamp(NOW - age), "document": stamp(NOW - age)},
        source="probe",
    )


async def test_a_stale_refusal_is_reprobed_and_an_accepted_answer_replaces_it(worlds):
    world = await only(worlds, NEW, Agent(), inputs=refused_inputs(timedelta(hours=25)))
    await refresh(world)
    assert asked(world, NEW) == ["control", "document"]
    row = known(world, NEW)
    assert row.accepted == ["image", "document"] and row.refused == {}
    assert row.probed_at["document"] == stamp(NOW)


async def test_a_fresh_refusal_is_not_reprobed(worlds):
    world = await only(worlds, NEW, Agent(), inputs=refused_inputs(timedelta(hours=3)))
    await refresh(world)
    assert asked(world, NEW) == []
    assert known(world, NEW).refused == {"document": 400}


async def test_an_unanswered_reprobe_keeps_the_refusal_and_its_date(worlds):
    old = timedelta(hours=25)
    agent = Agent({(NEW, "document"): status(429)})
    world = await only(worlds, NEW, agent, inputs=refused_inputs(old))
    await refresh(world)
    row = known(world, NEW)
    assert row.refused == {"document": 400} and row.probed_at["document"] == stamp(NOW - old)
    assert row.last_attempt_at["document"] == stamp(NOW) and row.unanswered_rounds == {
        "document": 1
    }
    world.upstream.agent_bodies.clear()
    await refresh(world)  # the same refresh window: no request is repeated
    assert asked(world, NEW) == []


async def test_a_stale_baseline_refusal_is_reprobed_after_the_merge_copies_it(worlds):
    world = await worlds(
        Upstream(agent=Agent({("xai/grok-4.3", "document"): bad(NAMED)})), quiet=False
    )
    await silence_baseline(world, only={ADDED_AFTER_THE_SWEEP})  # its inputs were never swept
    late = NOW.replace(month=11, day=12)  # the baseline's refusal is from 2026-10-30
    world.app.matrix.now = lambda: late
    await refresh(world)
    # image is unknown (asked); the document refusal is older than 24 hours (asked again)
    assert asked(world, "xai/grok-4.3") == ["control", "image", "document"]
    row = known(world, "xai/grok-4.3")
    assert row.refused == {"document": 400} and row.probed_at["document"] == stamp(late)


# --- failure handling ----------------------------------------------------------------------


async def test_a_cancel_mid_model_keeps_the_kinds_already_answered(worlds):
    import asyncio

    calls = []

    def agent(body, n):
        calls.append(key_of(body))
        if key_of(body) == "document" and body["model"] == NEW:
            raise asyncio.CancelledError
        return completed(n)

    world = await worlds(Upstream(models=payload_with(NEW), agent=agent))
    with pytest.raises(asyncio.CancelledError):
        await refresh(world)
    row = stored(world).models[NEW]
    assert "image" in row.inputs.accepted and row.probing_until is None


async def test_the_matrix_file_is_whole_after_an_input_round(worlds):
    world = await worlds(Upstream(models=payload_with(NEW), agent=Agent()))
    await refresh(world)
    loaded = matrix.load(path_of(world))
    assert loaded.state == "ok" and loaded.matrix.version == 1
    assert not list(path_of(world).parent.glob("model_matrix.*.tmp"))

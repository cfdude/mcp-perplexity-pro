# Design

## Context

`routing-rules-v1` (applied first) adds dynamic mode, `rules.classify`, `Route.reason`, the
follow-up floor and the standard-tier route for `search` false. `perplexity_decide` already sends
and records Decisions requests through `decisions.run_decide` and `costed.costed_call`; a recorded
`choice` answer carries `choice`, `confidence` and `probabilities`
(`tests/fixtures/decisions_choice.json`). See proposal.md for the motivation.

## Goals / Non-Goals

**Goals:**
- A network classifier for dynamic mode that can only improve or equal the rules' result: bounded,
  recorded, never fatal.
- Reuse the Decisions request and recording machinery; add no second costed-call sequence.

**Non-Goals:**
- No escalation (a retry on a weak answer), no accuracy or savings claim, no tuning of the
  threshold (the eval epic), no Router API backend, no change to explicit selectors.
- No new tool, migration or dependency.

## Decisions

**D1. `routing_decisions.py` holds `classify_dynamic(app, text, *, project, tool, floor_rules)`.**
It returns the same `Classification` shape as `rules.classify`, plus `source` (`rules` or
`decisions`). It is the only caller of the Decisions API for routing. `rules.py` stays pure and
unchanged. Alternative: put it in `routing.py`; rejected because `routing.py` is pure and
network-free (its module docstring says so, a test could pin it).

**D2. The request.** `{"model": DEFAULT_MODEL, "state": {"prompt": text[:4000]}, "questions":
{"tier": {"type": "choice", "criteria": {"light": ..., "standard": ..., "complex": ...}}}}` with
three fixed one-line criteria written for a router ("a short factual lookup", "an ordinary question
that needs a sourced answer", "an analytical, multi-part or long task"). Built by
`decisions.build_request` so the Decisions validators apply. Alternative: a `score` question
(0 to 2); rejected because a `choice` names the tier directly and returns a confidence per option.
The criteria are checked live in acceptance (a fixture is captured with
`tests/test_live_capture.py`, never hand-written).

**D3. The weak-answer rule.** Confidence under 0.5 means take the higher of the Decisions tier and
`rules.classify(text)`; at or above 0.5, the Decisions tier alone. The 0.5 is a starting value, not
a claim; `routing-eval-tuning` tunes it. The higher-wins direction is the quality-safe one (a
wrong `light` costs an answer, a wrong `complex` costs a few cents).

**D4. The bound.** `asyncio.timeout(3)` around the whole call, retries included, because the client
retries internally; a timeout cancels the in-flight request, which `costed_call` already handles
(a cancelled call is not recorded, an accepted gap; the timeout is reported as a fallback reason).
3 seconds is a constant, not a setting. Alternative: one attempt only (`max_attempts=1`);
rejected because it does not bound a slow first attempt.

**D5. Recording.** `decisions.run_decide` gains a keyword `tool` (default `TOOL`), so the event
carries the calling tool's name. `costed_call` already does validate, project commit, timed call,
`record_usage`, and records a failure with `status=exc.category`. The project is the call's own;
the classifier runs after the ask's project name validated. Alternative: a `routing` tool name;
rejected because the usage spec defines the event's tool as the MCP tool name.

**D6. Where it runs.** In `perplexity_ask`: validate options with a provisional route (the
standard tier's model, as the chat tool does for follow-ups in `routing-rules-v1`), then, if the
call is nameless, in dynamic mode, with the Decisions classifier and `search` not false, classify
and build the final route (floor applied for chat follow-ups). An invalid call therefore spends
nothing. A cancelled call during classification records nothing for the classifier (accepted gap,
same as every costed call).

**D7. Settings.** `PERPLEXITY_CLASSIFIER` in `settings.py`: `rules` default or `decisions`;
case-insensitive; used in dynamic mode only; `ignored_routing_vars()` warns in other modes. A
failure is `SettingsError` naming the variable.

**D8. Surfaces.** `Route` gains `classifier: str | None`; `Routing` (result) gains `classifier`;
`instructions_text`, `description_sentence`, the models section (`classifier`, plus the decider
model) and the help topic name it. `tests/test_tools_list_budget.py` (extended for dynamic in
`routing-rules-v1`) stays the gate.

## Risks / Trade-offs

- [Up to 3 s added to a nameless call] → bounded by D4, and only in dynamic mode with this
  classifier; explicit selectors skip it; acceptance records the observed latency.
- [The prompt goes to a second Perplexity endpoint] → the same provider and the same text the ask
  sends next; truncated to 4000 characters; documented in the README and help topic.
- [The 10 requests per second organization limit is shared with `perplexity_decide`] → a
  `rate_limited` answer falls back to the rules and is recorded, so it is visible.
- [The decider's choices drift or the criteria misfit] → the rules backstop it only on failure or
  weakness, so a confidently wrong answer is routed as given; mitigation is the eval epic and the
  reason/`classifier` fields that make each decision inspectable.
- [The Decisions API may be unavailable on a key (forbidden)] → falls back to the rules every call
  with a warning-level log naming the category (never the prompt) at most once a minute.

## Migration Plan

No data change. Default behavior is unchanged: `PERPLEXITY_CLASSIFIER` defaults to `rules`.
Rollback is unsetting the variable.

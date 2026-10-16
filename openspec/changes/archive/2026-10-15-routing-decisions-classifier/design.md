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

**D1. `routing_decisions.py` holds `classify_dynamic(app, text, *, project, tool)`.** It returns
a `Classification` (the shape of `rules.classify`, with a `classifier` field, `rules` or
`decisions`), having done the Decisions request and the weak-answer merge itself. It does not
touch the floor, the search-off rule or the route: `routing.resolve(..., classification=c,
previous=...)` (`routing-rules-v1` D5) owns those, so there is one place that builds the final
route and its reason suffixes. `rules.py` stays pure and unchanged. Alternative: put the network
call in `routing.py`; rejected because `routing.py` is pure and network-free.

**D2. The request.** `decisions.build_request(DecideOptions(state=text[:4000], questions={"tier":
{"type": "choice", "criteria": {...}}}))` with the default decider model and three fixed one-line
criteria written for a router ("a short factual lookup", "an ordinary question that needs a sourced
answer", "an analytical, multi-part or long task"). The state is a string (the common fixture shape);
`decisions._state` refuses a prompt that is an image data URL, which falls back to the rules with
the not-classifiable reason. The answer has `choice`, one `confidence` and `probabilities` per
option; `confidence` is not the chosen option's probability (in `decisions_choice.json` the top
probability is 0.6996 and the confidence 0.5493). The criteria are checked live and fixtures
captured with `tests/test_live_capture.py` after they are final; changing a criterion means
re-capturing. Alternative: a `score` question; rejected because a `choice` names the tier directly.

**D3. The weak-answer rule.** Strength is the probability of the chosen option (`probabilities`),
else `confidence`, else unreadable (trusted alone when the choice is a known tier). Under 0.5, take
the higher of the Decisions tier and `rules.classify(text)`, a tie going to Decisions; at 0.5 or
more, the Decisions tier alone. The 0.5 means "a majority of the probability mass", a starting
value that `routing-eval-tuning` tunes; acceptance records the observed strength distribution. The
higher-wins direction is the quality-safe one (a wrong `light` costs an answer, a wrong `complex` a
few cents). The classifier sees at most 4000 characters while the rules see all of them; the
length signal is rules-only, so a long prompt the decider saw truncated can still merge upward.

**D4. The bound, inside the recorded call.** The bound covers the single Decisions request;
the project commit and the usage write still wait on SQLite's busy timeout as every costed call does. The deadline (3 s, a constant) is fixed at the start
of `classify_dynamic` and the `call` lambda handed to `costed_call` wraps the request in
`asyncio.timeout` for the time left, converting `TimeoutError` into `PerplexityError("network_timeout")`.
The existing failure branch of `costed_call` then records the request with that status, so a
timeout is not an unrecorded cancel; a genuine client cancel still propagates (it is a
`CancelledError`, not folded into the fallback). The request is made once (`attempts=1`): the client's retry loop would sleep through a 429's
`Retry-After` until the deadline cut it off and mislabel it `network_timeout`, and a retry would add
latency to a call that has a fallback anyway.

**D5. Recording.** `decisions.run_decide` gains a keyword `tool` (default `TOOL`), so the event
carries the calling tool's name, as the usage spec defines the event's tool. `costed_call`
validates the project name, commits the project, makes the timed call and records; the caller
(`ask`, or `_send`) validates the project name before classifying so an invalid name is
refused as it is today and never swallowed as a fallback. The project commit then runs twice (the
classifier's and the ask's), a short write each; accepted. No third `record_usage(` call site is
added (CLAUDE.md).

**D6. Where it runs.** `perplexity_ask`: validate the project name and the options with a
provisional route (the standard tier's model, as the chat tool does for follow-ups in
`routing-rules-v1`), then, for a nameless dynamic call with the Decisions classifier and `search`
not false, `classify_dynamic`, then `resolve(..., classification=c)` for the final route. For a
chat follow-up it is skipped when the floor is already `complex` (the answer cannot change the
route); otherwise it runs after the chat lookup and after `last_route`, with that read-only unit
closed (a Decisions request is a costed call and must hold no write unit). Nothing else makes a
Decisions request for routing.

**D7. Settings.** `PERPLEXITY_CLASSIFIER` in `settings.py` as a plain `str` (a `Literal` field would fail startup in
standard mode and contradict the spec): `rules` default or `decisions`, case-insensitive,
checked in `_routing_problems` in dynamic mode only; elsewhere ignored with one warning
(`ignored_routing_vars()`). A failure is a `SettingsError` naming the variable.

**D8. Surfaces.** `Classification.classifier` flows to `Route.classifier` and `Routing.classifier`
(added by `routing-rules-v1`); `instructions_text`, `description_sentence`, the models section
(`RoutingSection.classifier` from `routing-rules-v1`, plus a new optional `decider_model`) and the
help topic name it. `tests/test_tools_list_budget.py` is extended to the largest variant (dynamic
with the Decisions classifier) and acceptance records the combined size of both changes.

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
- [The Decisions API may be unavailable on a key (forbidden)] → falls back to the rules every call;
  each failure is a recorded event and an INFO log naming the category, never the prompt (no
  once-a-minute throttle: it would need module-level state).

## Migration Plan

No data change. Default behavior is unchanged: `PERPLEXITY_CLASSIFIER` defaults to `rules`.
Rollback is unsetting the variable.

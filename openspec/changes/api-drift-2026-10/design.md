# Design

## Context

`acceptance/drift-review.md` holds the evidence (2026-10-29, live calls with the funded key). The
facts this design rests on: `POST /v1/agent` accepts `effort` and the deprecated `preset`, both
return 200 and the same model; responses carry BOTH fields with versioned values; the Decisions
API accepts the five names of the proposal and echoes the name asked for, with equal token counts
for equal input; the live pricing page gained a table that our price parser trips on.

## Decisions

**D1. Send `effort`, read as before.** Only the two request builders change (`agent.build_request`
and the research submit). The recorded and stored `preset` already comes from the REQUEST options,
not the response (design of py-agent-api), so versioned response values change nothing stored. We
keep the tool argument `depth` and the column names `preset` (no migration: a rename buys nothing
and costs a downgrade story). A fixture of a real response proves the tolerant read; no code in
the digest reads `effort` or `preset` from a response, and a test pins that.

**D2. The preset table is documentation, dated.** `catalog.PRESETS` is edited by hand to the
documentation of 2026-10-29. `ultra-preview` is not added: no tool offers it (research depths stay
`medium`, `high`, `xhigh`); it is an input to `routing-v2`.

**D3. Decisions: accept all names, price by name, keep the default.** `decisions.MODELS` grows to
the seven names. `pricing.DECISIONS_NANO_PER_INPUT_TOKEN` becomes a complete table keyed by model
(20 nano-USD for every accepted name except `pplx-decider-flash-v1.2` and
`pplx-decider-flash-latest`, 10), and `decisions_cost_nano(model, input_tokens)` takes the model; a
name missing from the table is an unknown cost (`none`), never a silent $0.02. The `latest`
aliases are priced as their current target (v1.2 and flash-v1.2); if Perplexity re-points an
alias, the documented price table is the thing that changes, dated by `PRICES_AS_OF`.
The default stays `pplx-decider-v1.1-27b`, and so does the classifier's model: on one example
flash and v1.2 answered differently from v1.1, and a default is a behavior change that needs the
`routing-eval-tuning` evaluation, not a guess. Images stay refused (non-goal).
Redaction: the exemption for documented `pplx-decider-*` ids is a prefix rule, so the new names
need no code change, but a test pins every accepted name as stored verbatim.

**D4. The pricing parser reads every table under a heading.** `tests/pricing_page.py` stops after
the first contiguous table; it now collects rows from each table under a heading and skips a row
with no price instead of raising, while still failing when a price the code depends on is missing
(the test's job). The fixture excerpt is re-recorded from the live page, with its `.meta.json`.
`PRICES_AS_OF` moves to 2026-10-29 only after `tests/test_pricing_live.py` passes against the live
page; the stored `price_table` of old events keeps its old date by design.

## Risks

- A later removal of `preset` is why this is done now; the risk of the change itself is a request
  the API rejects. Mitigation: a live ask, chat send and research submit at the end (task 6.1).
- The `latest` aliases are priced by assumption (their current target). A wrong price is a wrong
  lower bound, labelled `computed` and dated; the live decide calls compare the reported token
  counts and the recorded cost.
- Equal token counts across decider versions were seen on one input; the price table is by name
  and does not depend on it.

## Out of scope (recorded)

`ultra-preview` as a depth, the Decisions default and classifier model, Decisions images,
documents and images as Agent inputs (`media-inputs`), a friendlier credit error (the upstream 403
text is already exact).

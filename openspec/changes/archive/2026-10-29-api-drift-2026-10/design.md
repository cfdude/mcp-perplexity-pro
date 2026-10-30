# Design

## Context

`acceptance/drift-review.md` holds the evidence (2026-10-29, live calls with the funded key). The
facts this design rests on: `POST /v1/agent` accepts `effort` and the deprecated `preset`, both
return 200 and the same model; responses carry BOTH fields with versioned values; the Decisions
API accepts the five names of the proposal and echoes the name asked for, with equal token counts
for equal input; the live pricing page gained a table that our price parser trips on.

## Decisions

**D1. Send `effort`, read as before.** (A research snapshot's `model` may now be a versioned preset such as `medium@2026-10-16.0`; for a queued, in-progress or cancelled snapshot `snapshot_model` still ignores it (no `/`), and a completed snapshot keeps its model verbatim, as today; a test pins both.) Only the two request builders change (`agent.build_request`
and the research submit). The recorded and stored `preset` already comes from the REQUEST options,
not the response (design of py-agent-api), so versioned response values change nothing stored. We
keep the tool argument `depth` and the column names `preset` (no migration: a rename buys nothing
and costs a downgrade story). A fixture of a real response proves the tolerant read; no code in
the digest reads `effort` or `preset` from a response, and a test pins that.

**D2. The preset table is documentation, dated.** `catalog.PRESETS` is edited by hand to the
documentation of 2026-10-29. `ultra-preview` is not added: no tool offers it (research depths stay
`medium`, `high`, `xhigh`); it is an input to `routing-v2`.

**D3. Decisions: accept all names, price by the requested name, keep the default.** The live page
documents only two rows (`pplx-decider-v1.2` $0.02, `pplx-decider-flash-v1.2` $0.01) and notes that
the old names bill as v1.2 and the `latest` aliases at the model they select. So
`pricing.DECISIONS_NANO_PER_INPUT_TOKEN` keeps ONLY the page's rows (the pricing guard compares it
to the page), and a separate `DECISIONS_PRICED_AS` maps every other accepted name to a row
(`pplx-decider-v1.1-27b`, `pplx-decider-v1-27b`, `pplx-decider-latest`,
`perplexity/pplx-decider-latest` to v1.2; `pplx-decider-flash-latest` and
`perplexity/pplx-decider-flash-latest` to flash-v1.2). `decisions_cost_nano(model, input_tokens)`
resolves through it; a name in neither is an unknown cost (`none`), never a silent $0.02. The model
priced is the one the REQUEST named (`body["model"]` in `run_decide`'s interpreter), not the one a
response echoes, because a response may echo another name or omit it. `decisions.MODELS` is the
eight accepted names. The default stays `pplx-decider-v1.1-27b`, and so does the classifier's
model: on one example flash and v1.2 answered differently from v1.1, and a default is a behavior
change that needs the `routing-eval-tuning` evaluation, not a guess. Images stay refused.
Redaction: the exemption is a prefix rule, so the new names need no code change; a test pins every
accepted name stored verbatim.

**D4. The pricing parser reads the first table under each heading.** Today `extract_tables` merges
every `|` line under a heading, so the extra billing-units table becomes data rows and raises. It
stops at the first contiguous table per heading (as the proposal says) and still raises on a
malformed row, so a dropped price cannot hide. The excerpt is re-recorded from the live page
(`.meta.json` too), the count assertion in `tests/test_pricing.py` follows the new row count, and
the Decisions notes (old names, aliases) are recorded in the excerpt and asserted by a test
against `DECISIONS_PRICED_AS`. The pricing constants, the parser, the re-record and the test edits
land in ONE commit, because the pricing test is red between any two of them. `PRICES_AS_OF` moves
to 2026-10-29 in that commit; every test and README date that names 2026-10-09 moves with it
(`tests/test_usage_types.py`, `tests/test_pricing.py`, README lines naming the date).

## Risks

- A later removal of `preset` is why this is done now; the risk of the change itself is a request
  the API rejects. Mitigation: a live ask, chat send and research submit at the end (task 5.1).
- The `latest` aliases are priced by assumption (their current target). A wrong price is a wrong
  lower bound, labelled `computed` and dated; the live decide calls compare the reported token
  counts and the recorded cost.
- Equal token counts across decider versions were seen on one input; the price table is by name
  and does not depend on it.

## Out of scope (recorded)

`ultra-preview` as a depth, the Decisions default and classifier model, Decisions images,
documents and images as Agent inputs (`media-inputs`), a friendlier credit error (the upstream 403
text is already exact).

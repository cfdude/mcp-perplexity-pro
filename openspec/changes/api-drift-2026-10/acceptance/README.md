# Live acceptance, api-drift-2026-10 (task 5.1)

Run 2026-10-29 against the real API with the funded key (key loaded from the environment of each
command only; never printed or stored). Code under test:
branch `epic/api-drift-2026-10` at `49441d6`. The live pm2 app and port 8102 were not touched.

Method: the `perplexity-pro` command (in-process FastMCP client, same tool code as the server) with
a temporary `PERPLEXITY_DATA_DIR` (deleted afterwards), run through a throwaway wrapper that prints
the key set of every outgoing request body (never headers) so the wire fields are observed, not
inferred. No server process was started, so no port was used.

## (a) Agent API, `effort` on the wire

| Call | Wire body keys | `effort` sent | `preset` sent | Result | Recorded preset | Cost (reported) |
|---|---|---|---|---|---|---|
| ask depth fast | effort, input, store | `fast` | no | ok, `openai/gpt-6-luna` | fast | $0.00122 |
| ask depth medium | effort, input, store | `medium` | no | ok, `openai/gpt-6-luna` | medium | $0.00143 |
| chat send (new, depth fast) | effort, input, store | `fast` | no | ok | fast | $0.00131 |
| chat follow-up (no depth, standard routing) | input, max_steps, model, previous_response_id, store, tools | n/a (names `perplexity/sonar`) | no | ok, chained | none (model route) | $0.00071 |
| chat follow-up (depth fast) | effort, input, previous_response_id, store | `fast` | no | ok, chained | fast | $0.00196 |
| research submit medium | background, effort, input, store | `medium` | no | queued, then completed in ~25 s | medium | $0.00138 |

The research job was observed with `jobs status` then `jobs result` (completed, `usage_recorded`
true, answer correct). No request carried `preset`. The follow-up without a depth is the
unchanged model path of standard routing; a second follow-up with a depth covered the `effort`
path on a chained turn.

## (b) Decisions API, one identical question set

State: "My invoice was charged twice and I need it fixed today." Questions: one `noul`, one
`choice`.

| Requested model | Wire `model` | Result `model` | Event model | input_tokens | cost_usd | Check |
|---|---|---|---|---|---|---|
| `pplx-decider-v1.2` | same | `pplx-decider-v1.2` | `pplx-decider-v1.2` | 136 | 0.00000272 | 136 x 20 nano = 2720 |
| `pplx-decider-flash-v1.2` | same | `pplx-decider-flash-v1.2` | `pplx-decider-flash-v1.2` | 201 | 0.00000201 | 201 x 10 nano = 2010 |
| `pplx-decider-latest` | same | `pplx-decider-latest` | `pplx-decider-latest` | 136 | 0.00000272 | priced as v1.2: 136 x 20 = 2720 |

Flash costs exactly half v1.2 per token (10 vs 20 nano-USD). Its token count was 201 against 136 on
the same input, so the flash call's total was not half; the Decisions tokenization differs by
model (the design's "equal counts" observation held for v1.1 vs v1.2 and `latest`, not flash). The
price table is by name and does not depend on it. All three costs are `computed`.

## (c) Live tests

`PERPLEXITY_API_KEY=... uv run pytest -m live tests/test_agent_live.py tests/test_client_live.py
tests/test_pricing_live.py`: 3 passed, 3 deselected, 13.39 s. No test needed a fix (none reads
`preset`). The run overwrote four tracked fixtures (`agent_chat_depth_switch` and
`agent_chat_replay`, each `.json` and `.meta.json`) with fresh captures; `git diff` showed new
response ids, the capture date, and the versioned values (`effort`/`preset` of `low@2026-10-24.0`
and `fast@2026-10-16.0`), and dropped the `request_edit_note`. They were restored with
`git checkout tests/fixtures`; the tree was clean afterwards. The live tests' own spend is not
measured here (their captures are discarded); it is two chat turns of the order of $0.002 each.

## (d) Reconciliation

`perplexity_usage` (grouped by tool) against the sum of the per-call costs above:

| Tool | Calls | Sum of per-call costs (nano-USD) | `perplexity_usage` (nano-USD) |
|---|---|---|---|
| perplexity_ask | 2 | 1220000 + 1430000 = 2650000 | 2650000 |
| perplexity_chat | 3 | 1310000 + 710000 + 1960000 = 3980000 | 3980000 |
| perplexity_research | 1 | 1380000 | 1380000 |
| perplexity_decide | 3 | 2720 + 2010 + 2720 = 7450 | 7450 |
| Total | 9 | 8017450 | 8017450 ($0.00801745) |

Exact match to the nano-USD; 0 errors, 0 unknown costs, 3 computed (the decides), 6 reported.
The nine events carry the models above (the `sqlite3` read of `usage_events` agrees).

## Spend

$0.00801745 recorded by the scratch instance, plus the three live tests (not measured, estimated
under $0.01). Total well under the approved $0.15.

## Tool list size

Untouched: this task changed no tool, schema or description, so the `tools/list` figure recorded in
`CLAUDE.md` is unchanged.

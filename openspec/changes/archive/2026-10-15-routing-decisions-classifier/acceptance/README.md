# Acceptance record: routing-decisions-classifier

## Task 2.1: tools/list size (measured 2026-10-15)

Method: `tests/test_tools_list_budget.py` builds a server through `build_server` with a dummy key
and one `tools/list` POST over HTTP on an ephemeral port (not the live pm2 app); the byte count is
`len(response.content)`. Budget: 59779 bytes.

| Server | Bytes |
|---|---|
| default (standard routing) | 56545 |
| dynamic, rules classifier | 56831 |
| dynamic, Decisions classifier | 57065 |

Combined size of both routing changes: the last recorded figure before them is 55512 bytes (eleven
tools, live server, 2026-10-13, agent-help acceptance, quoted in the test's comment). The dynamic
server with the Decisions classifier is 57065 bytes, +1553 bytes (+2.8%) over that figure, and
2714 bytes under the budget. The two measurements use different servers (live against test), so the
difference is an indication, not an exact attribution.

## Live acceptance (task 3.1), 2026-10-15

Run on scratch data directories, never the live pm2 app, with `PERPLEXITY_ROUTING=dynamic` and
`PERPLEXITY_CLASSIFIER=decisions`, the real key from the environment. Raw outputs are the
numbered files here (`10-labeled-set-decisions.json`, `01` to `08`).

**The labeled set through `classify_dynamic` (44 requests, one at a time, tool `perplexity_ask`).**
These numbers are observations, not claims: the labels were written by us to pin the rules, so the
rules agreeing more than the decider says nothing about which is better.

| | Decisions path | rules alone |
|---|---|---|
| exact agreement with the label, all 44 | 38 | 41 |
| exact agreement, the 37 `clear` prompts | 33 | 37 |
| within one tier of the label | 44 | 44 |

- 42 of 44 results came from the Decisions answer; in 2 the rules supplied the tier after a weak
  answer (3 answers were weak: a probability under 0.5). No request failed or timed out.
- Where the Decisions path differed from the label: 4 `standard` prompts went to `complex`, 1
  `light` went to `standard`, 1 `complex` went to `standard`. The decider leans up on ordinary
  questions; a `complex` route costs a `medium` run, so this is the cost side of the quality-safe
  choice and is left for `routing-eval-tuning`.
- Latency of the classification: min 0.246 s, median 0.264 s, p90 0.274 s, max 0.675 s, far inside
  the 3 s bound.

**Real calls** (the CLI in-process, the same tool code as over MCP):

| call | routing | ran | cost (reported) |
|---|---|---|---|
| 01 lookup | tier light, `classifier` decisions, `decisions: light (0.94)` | preset fast | $0.0012 |
| 02 an ordinary 220-character question | tier complex, `decisions: complex (0.51)` | preset medium, 55.7 s | $0.01796 |
| 03 explicit `--model` | `selected_by` model, no classifier, no Decisions request | `perplexity/sonar` | $0.00014 |
| 04 `--no-search` | `selected_by` default, reason `search off`, no Decisions request | `perplexity/sonar` | $0.00008 |
| 05 chat turn 1 | tier standard, `decisions: standard (0.87)` | `perplexity/sonar` | $0.00388 |
| 06 chat turn 2 `and for async?` | `decisions: light (0.51), held at standard` | `perplexity/sonar` | $0.00504 |

- The same ordinary question that the rules route to `standard` ($0.005, about 10 s in the
  `routing-rules-v1` acceptance) the decider routed to `complex` at probability 0.51, just over the
  0.5 line: $0.018 and 55.7 s. That is the over-escalation seen in the labeled set, on a real call.
- Ledger: 6 `agent` events and 4 `decisions` events (calls 01, 02, 05 and 06; the explicit-model
  and search-off calls made none), tool `perplexity_ask` for 6 and `perplexity_chat` for 4; the
  four Decisions events cost 12,660 nano-USD in total (about 3,165 each, roughly 158 input
  tokens); the whole run cost $0.02831266 and reconciles to the nano-USD with the per-call
  figures.

# Acceptance record: routing-rules-v1

## tools/list size (task 4.1)

Measured 2026-10-15 with one `tools/list` POST to a real HTTP runner (`tests/server_support.py`
`serving`, an ephemeral port, a dummy key, a temporary data directory), on the working tree of the
task 4.1 commit (parent `bfedb68`). Eleven tools in each case. The cap is 59779 bytes
(`tests/test_tools_list_budget.py`, parametrized over a default and a dynamic server).

| Server | Bytes | Against 59779 |
|---|---|---|
| default (`standard` mode) | 56367 | 3412 below |
| `dynamic` mode, no tier variables | 56581 | 3198 below |

For comparison, the same measurement on the parent commit (`bfedb68`, before the `perplexity_models`
routing fields and the reworded `tier` descriptions) gave 56024 for both modes. The growth is the
`preset` and `classifier` fields of the models routing section (+343 bytes in a default server) and
the dynamic wording of the instructions and the ask and chat descriptions (+214 more in dynamic mode).

## Live acceptance (task 5.1), 2026-10-15

Run through the real CLI in-process (`perplexity-pro ... --json`, the same tool code as over MCP)
with `PERPLEXITY_ROUTING=dynamic`, the real key from the environment and a temporary data
directory; the live pm2 app was not touched. Raw outputs are the numbered `.json` files here.

| call | routing | model that ran | latency | cost (reported) |
|---|---|---|---|---|
| 01 lookup (`What is the latest stable Python release?`) | tier light, `classifier` rules, reason `short lookup` | `openai/gpt-6-luna` (preset fast) | 2.1 s | $0.0012 |
| 02 ordinary 220-character question | tier standard, reason `no signals` | `perplexity/sonar` | 10.7 s wall | about $0.005 |
| 03 explicit `--model perplexity/sonar` | `selected_by` model, classifier null | `perplexity/sonar` | 3.1 s | about $0.003 |
| 04 `--no-search` on the lookup query | first try: upstream `failed` (finish_reason=error); two retries: tier standard, `selected_by` default, reason `search off` | `perplexity/sonar` | | $0.00012 to $0.00014 |
| 05 long comparison | tier complex, reason `4 analysis terms` | `openai/gpt-6-luna` (preset medium) | 108.1 s | $0.0376 |
| 06 chat turn 1 | tier standard | `perplexity/sonar` | 5.0 s | |
| 07 chat turn 2, `and for async?` | tier standard, reason `no signals` (floor not needed) | `perplexity/sonar` | 4.1 s | $0.00504 |

- Total spend of the run, from the ledger: $0.05357 over 7 calls (one failed, unknown cost), well
  under the $0.25 cap; the ledger by tool matches the per-call figures.
- The `medium` run took 108 s against the 120 s synchronous read timeout (`PERPLEXITY_AGENT_READ_TIMEOUT`):
  the risk named in design.md is real, and one more slow run would have been billed but unreadable.
  The same exposure already exists for an explicit `depth` `medium`; recorded, not changed here.
- Reported versus requested model ids: `perplexity/sonar` came back as `perplexity/sonar`, and
  preset `fast` and `medium` runs report `openai/gpt-6-luna`, so a stored preset (not the model)
  is what identifies a preset tier, as `tier_of` assumes. No `anthropic/` id was run (nothing
  routes there by default); the tie and no-match paths fall back to `standard`.
- The lookup and ordinary-question routes landed where the labeled set expects. Seven calls are
  too few to say anything about accuracy, and none is claimed.

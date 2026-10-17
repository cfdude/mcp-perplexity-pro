# Evidence for model-matrix

## Effort probe of all 54 live models, 2026-10-17 (before any code)
`effort-probe-2026-10-17.json`: 378 calls (54 models x none, minimal, low, medium, high, xhigh,
max), prompt "Reply with the single word OK.", `max_output_tokens` 300, no tools, `store` false,
through `POST /v1/agent` with `reasoning.effort`. Total cost $0.197 (reported), about $0.0036 per
model. The live list had 54 ids that day (the docs page lists 40).

| Result | Models |
|---|---|
| accept every level (none to max) | 45 of 54 |
| reject `xhigh` and `max` (HTTP 400 `invalid request`) | `openai/gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-5.1`, `perplexity/kimi-k3` |
| reject `minimal` only | `google/gemini-3.1-pro-preview` |
| reject every level, accept only no effort | `perplexity/deepseek-v4-pro-0813`, `xai/grok-4.20-multi-agent`, `xai/grok-4.20-reasoning` |

Accepted at least once: minimal 50, low 51, medium 51, high 51, xhigh 46, max 46 (of 54).

- Perplexity's docs say Kimi K3 accepts `xhigh` and `max`; the live API refused both. The docs
  lag the API again (`docs/lessons/docs-lie-probe-the-api-first.md`).
- The error body for a refusal is only `invalid request`; an invalid value outside the known
  vocabulary is refused with `effort must be one of: none minimal low medium high` (a list that
  omits the two levels most models accept).
- Accepted does not mean effective: an earlier 9-model probe (`docs/research/2026-10-15-model-benchmarks/`)
  showed reasoning tokens moving with effort for only 3 models on a trivial prompt.

## `tools/list` size and one full `perplexity_models` result, 2026-10-18 (task 5.1)
Measured offline on the test servers (an ephemeral-port HTTP server on `build_server`, a dummy key,
a temporary data directory, a `MockTransport` serving the recorded 54-model list; the same method
as `tests/test_tools_list_budget.py`), before and after the `efforts` and `matrix` output fields:

| Server | `tools/list` before (bytes) | after (bytes) | change | budget |
|---|---|---|---|---|
| default | 56545 | 57567 | +1022 | 59779 |
| dynamic | 56831 | 57853 | +1022 | 59779 |
| dynamic with the Decisions classifier | 57065 | 58087 | +1022 | 59779 |

The `perplexity_models` entry alone grew from 3770 to 4792 bytes. Headroom under the budget is now
1692 bytes on the dearest server.

One full `perplexity_models` call (no arguments, 54 models, the packaged baseline, default
routing), measured as the JSON-RPC `tools/call` response over HTTP:

| Part | Before | After |
|---|---|---|
| whole HTTP response | 13869 | 20328 |
| `content[0].text` (the readable table) | 4627 | 5395 |
| `structuredContent` (compact JSON) | 9067 | 14757 |

Each model gained `efforts` (about 100 bytes: two short lists and the source) and the result gained
the `matrix` object; the text gained an `efforts` column and one `Matrix:` line.

## Live acceptance (task 6.1), 2026-10-17

Four scratch servers (`mcp-perplexity-pro --transport http` on ephemeral ports, temporary data
directories, the real key from the environment; the live pm2 app untouched) driven by a harness
that calls the tools over HTTP. Raw outputs: `live/summary.json` and the four server logs (the
harness asserts the key appears in none of them).

| Step | Result |
|---|---|
| (a) no file, default settings | the server answered `/health` 0.73 s after start; the first `perplexity_models` call returned efforts with `matrix.origin` `baseline` |
| (b) after the first refresh | `model_matrix.json` exists, mode 0600, 54 models, `fetched_at` set, 0 models unprobed, origin `file`; the usage ledger holds no `model_matrix` event (no probe was needed: the baseline knows all 54) |
| (c) the live probe through the server path | a file whose `openai/gpt-6-luna` row was cleared to `unprobed`: the refresh probed it, 7 events (control and six levels) with tool `model_matrix`, API `agent`, no errors, cost reported as $0 (a trivial prompt on a $0.10 per million model); the result (`accepted` all six levels, `refused` none, source `probe`, lease cleared) equals the baseline row, a live consistency check of the baseline; `perplexity_usage` groups the events under `(none)` and `perplexity_projects list` shows no project |
| (d) `PERPLEXITY_MATRIX_PROBE=off` | the same cleared row stayed `unprobed` after the refresh and no event was recorded |
| (e) the models endpoint unreachable (`PERPLEXITY_BASE_URL` pointing at a closed port) | the server started and stayed healthy, exactly one warning (`model matrix refresh failed: [network_timeout] ... ConnectError`), and SIGTERM exited 0 in 0.39 s; `perplexity_models` itself returns its upstream error (it needs the live list, as before this change), so the baseline matrix is not visible through any tool when the list cannot be fetched; the matrix in memory is the baseline |

- SIGTERM exits took 0.39 to 0.49 s in all four runs.
- Spend: $0 reported for the seven probe requests, so the ledger total reconciles trivially
  (0 nano-USD); the earlier evidence run priced 54 models at $0.197.
- Not exercised live: a new model the baseline lacks (none exists today); the unit tests cover it
  with a mocked list.

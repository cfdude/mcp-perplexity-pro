# Live acceptance outputs, 2026-10-11 (tasks 6.1-6.3)

Real `tools/call` results (the `result` member) from the running pm2 server on `localhost:8102`
(this branch, restarted; `/health` 2.0.0, nine tools listed including `perplexity_decide`, data
directory listing unchanged, usage total 10 calls / 31810000 nano-USD before and after the
restart), against the live Perplexity API, project `acceptance-decide`. No key appears in any
file (scanned).

| File | Call |
|---|---|
| `d1.json` | `perplexity_decide`, default model, a noul, a choice and a score question about a support ticket (object state) |
| `d2.json` | `perplexity_decide`, `pplx-decider-v1-27b`, one score question about a text state |
| `x1.json` | blank state: `invalid_request`, nothing sent |
| `x2.json` | an `image_url` part in the state: `invalid_request`, nothing sent |
| `usage_by_tool.json`, `usage_by_api.json` | `perplexity_usage` for the project by tool and by api |
| `usage_after_delete.json` | the same report by name after the project was deleted (2 rows retained) |

Reconciliation: 2 calls, 0 errors, `calls_cost_unknown` 0, 9060 nano-USD ($0.00000906) =
346 input tokens x 20 + 107 x 20 = 6920 + 2140; the api grouping names only `decisions`.

console: not observable (Rob waived the manual console read on 2026-10-11; the computed cost of 20 nano-USD per input token stands unverified against the provider's console)

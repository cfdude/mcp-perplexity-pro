# Live acceptance outputs, 2026-10-11 (tasks 6.1-6.3)

Real `tools/call` results (the `result` member) from the running pm2 server on `localhost:8102`
(this branch, restarted; `/health` 2.0.0, eight tools listed, data directory listing unchanged,
no migration, usage total 7 calls / 24810000 nano-USD before and after the restart), against the
live Perplexity API, project `acceptance-search`. No key appears in any file (scanned).

| File | Call |
|---|---|
| `a1.json` | `perplexity_search` fast, `domains: [python.org]`, 3 results |
| `a2.json` | `perplexity_search` fast, three queries, `recency: week` (merge warning) |
| `a3.json` | `perplexity_search` web, `domains: [-reddit.com]`, `languages: [en]` |
| `x1.json` | mixed domains: `invalid_request`, nothing sent |
| `x2.json` | `recency` with `after`: `invalid_request`, nothing sent |
| `usage_by_tool.json`, `usage_by_api.json` | `perplexity_usage` for the project by tool and by api |
| `usage_after_delete.json` | the same report by name after the project was deleted (3 rows retained) |

Reconciliation: 3 calls, 0 errors, `calls_cost_unknown` 0, 7000000 nano-USD ($0.007) =
0.001 + 0.001 + 0.005; the api grouping names only `search`.

console: not observable (Rob waived the manual console read on 2026-10-11; the computed cost of one unit per request stands unverified against the provider's console)

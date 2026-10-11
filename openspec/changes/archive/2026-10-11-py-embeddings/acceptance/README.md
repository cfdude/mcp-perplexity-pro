# Live acceptance outputs, 2026-10-11 (tasks 10.1-10.3)

Real `tools/call` results (the `result` member) from the running pm2 server on `localhost:8102`
(this branch, restarted), against the live Perplexity Embeddings API, project `acceptance-embed`.
After the restart `/health` returns 2.0.0, `tools/list` names ten tools including
`perplexity_embed`, the database is at revision `0005` with the `embedding_chunks` table and its
four indexes, the data directory gained exactly `backup-0004.db` (the backup taken before the
migration), and `perplexity_usage` reported the same total (12 calls, 31819060 nano-USD) before and
after. No key appears in any file (scanned), and no base64 vector appears in any result (scanned).

| File | Call |
|---|---|
| `i1.json` | `index` of five short texts on three topics (bread, asyncio, volcanoes), 0.6b, default 1024 `int8` |
| `s1.json`, `s2.json` | `search` "how do I make crusty bread at home" and "running coroutines concurrently in Python", top 3 |
| `i2.json`, `s3.json` | `index` of the same texts with the 4b model, 256 dimensions, `binary`; `search` "what makes a volcano erupt" over them |
| `i3.json` | the same `index` repeated: nothing sent, nothing recorded (re-run after the zero-request cost display was fixed) |
| `st1.json` | `status`: the two stored combinations |
| `x1.json`, `x2.json` | dimensions 130 and a blank text: `invalid_request`, nothing sent |
| `d1.json`, `st2.json` | `delete` with `confirm` (10 chunks) and `status` afterwards (no groups) |
| `usage_by_tool.json`, `usage_by_api.json`, `usage_after_delete.json` | `perplexity_usage` for the project by tool and by api, and by name after the project was deleted (5 rows retained) |

Search quality (the sanity check): the bread query's best hits are `baking` and `sourdough`, the
asyncio query's are `tasks` and `python`, the volcano query's best hit is `volcano` (0.719).

Reconciliation: 5 calls (2 index requests, 3 searches), 0 errors, `calls_cost_unknown` 0, 4086
nano-USD ($0.000004086) = 456 + 3420 + 36 + 24 + 150, every cost `reported` by the API (its
`usage.cost.total_cost`); the api grouping names only `embeddings`.

console: not observable (Rob waived the manual console read on 2026-10-11; the cost is the provider's own reported figure in each response)

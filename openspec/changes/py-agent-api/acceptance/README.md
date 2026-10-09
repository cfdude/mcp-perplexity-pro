# Live acceptance outputs, 2026-10-09 (tasks 6.1-6.3)

Real `tools/call` results (the `result` member) from the running server on `localhost:8102`
against the live Perplexity API, project `acceptance`. No key appears in any file (scanned).

| File | Call |
|---|---|
| `a1.json` | `perplexity_ask` depth fast, `domains: [python.org]` |
| `a2.json` | `perplexity_ask` depth low |
| `c1.json`, `c2.json` | `perplexity_chat` send, two turns (`c2` answers from `c1`) |
| `r1.json` | `perplexity_research` submit (medium) |
| `j2.json` | `perplexity_jobs` result of the completed run |
| `k1.json`, `k2.json` | cancel of the second run, then `status` showing `cancelled` |
| `jl.json` | `perplexity_jobs` list |
| `u_tool.json`, `u_day.json` | `perplexity_usage` grouped by tool and by day |
| `d1.json`, `u3.json` | `perplexity_projects` delete, then the usage report by name afterwards |

Reconciliation: 6 calls, 1 error (the cancelled run), 22970000 nano-USD ($0.02297) =
0.00143 + 0.00156 + 0.00118 + 0.00158 + 0.01722; `calls_cost_unknown` 1.

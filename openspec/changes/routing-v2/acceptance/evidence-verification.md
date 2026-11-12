# Evidence verification (routing-v2 tasks 2.2 and 2.3)

Retrieved 2026-11-11. Every figure below was read at the vendor or benchmark page named in its
`source_url` (an LLM Stats lead is never itself verification). Leads came from the owner-run
worksheet `acceptance/scripts/llm_stats_leads.py` (8 shortlist ids, 7 data responses, no
`/v1/scores`); its output stayed outside the repository.
Data by LLM Stats (linked to https://llm-stats.com).

A score of `data/routing_evidence.json` is on a 0 to 100 scale (the lead's 0.648 is 64.8).

## Verified figures (9 entered)

| Model | Benchmark id | Score | Source read | Quoted snippet |
|---|---|---|---|---|
| `anthropic/claude-haiku-5-5` | `terminal_bench_4_0` | 39.2 | anthropic.com/claude-haiku-5-5 (announcement 2026-10-07) and its system card, section 8.4 | "Claude Haiku 5.5 scored 39.2% on Terminal-Bench 4.0 with safeguards enabled." (card); page: 39.2% under "Agentic coding" |
| `anthropic/claude-haiku-5-5` | `swe_bench_pro` | 64.8 | system card 8.1 table and 8.2 (PDF read as text) | "SWE-Bench Pro ... Claude Haiku 5.5 achieved 64.8%." (mean of five trials) |
| `anthropic/claude-sonnet-5-5` | `terminal_bench_4_0` | 70.6 | anthropic.com/claude-sonnet-5-5 (2026-09-28) and card 8.5 | "Sonnet 5.5 scores 70.6% on Terminal-Bench 4.0" (page); "Claude Sonnet 5.5 scored 70.6% on Terminal-Bench 4.0 with safeguards enabled" (card) |
| `anthropic/claude-sonnet-5-5` | `swe_bench_pro` | 81.3 | card 8.1 table and 8.2 | "Sonnet 5.5 achieved 81.3%." |
| `anthropic/claude-opus-5-5` | `terminal_bench_4_0` | 66.4 | anthropic.com/claude-opus-5-5 (2026-09-22), table with footnote "reported for Claude Opus 5.5 at xhigh effort"; card 8.5 | card: "Claude Opus 5.5 scored 66.36% on Terminal-Bench 4.0 with safeguards enabled" (rounded to 66.4, the page figure) |
| `anthropic/claude-opus-5-5` | `swe_bench_pro` | 89.9 | card 8.1 table and 8.2 | "Claude Opus 5.5 achieved 89.9%." |
| `google/gemini-3.8-flash` | `terminal_bench_4_0` | 19.1 | Google DeepMind model evaluation PDF behind deepmind.google/models/evals-methodology/gemini-3-8-flash/ (results "as of September, 2026"), rendered page 4 | row "Terminal-bench 4.0 / General agent capabilities", column Gemini 3.8 Flash: 19.1%; methodology: "reported from the official public leaderboard ... the highest scoring thinking level" |
| `perplexity/sonar` | `browsecomp` | 7.0 | docs.perplexity.ai/docs/agent-api/migrate-from-sonar/benchmarks.md | table row Sonar: "7.00%", benchmark BrowseComp (arXiv 2504.12516), "the baseline those models were measured against before retirement" |

`as_of` is the announcement date for the Anthropic figures. The Google and Perplexity pages state
no day (a month, and none), so their `as_of` is the retrieval date 2026-11-11 and `verified_at` is
the same day. `harness` is the harness the source names, or null when it names none.

## Leads checked against their sources

| Lead (LLM Stats) | Source read | Agreement |
|---|---|---|
| haiku-5-5 `swe-bench-pro` 0.648, `terminal-bench-4.0` 0.392 | card and page | agree |
| sonnet-5-5 0.813, 0.706 | card and page | agree |
| opus-5-5 0.899, 0.664 | card and page | agree |
| gemini-3.8-flash `terminal-bench-4.0` 0.191 | evaluation PDF | agrees |
| gpt-6.1-terra `terminal-bench-4.0` 0.503 | openai.com page answered HTTP 403 to the fetch tool and to curl | NOT verified, NOT entered. Secondary reports quote 50.3 (vendor) and 55.6 (an Artificial Analysis figure) and disagree with each other |
| gpt-6-luna, gpt-6.1-sol | no matching row | nothing to verify |

## Not found, so absent (the router falls back for these)

- `gpqa_diamond`: no shortlist model has a Diamond figure at a source I could read (the Anthropic system
  cards mention GPQA only in a controllability test; an LLM Stats `gpqa` row is a 448-question set and is
  never entered as Diamond). Reasoning class: 0 eligible models.
- `browsecomp`: only `perplexity/sonar` (7.0). No vendor page for the other seven shortlist models gives a
  GPT-6.x, Claude 5.5 or Gemini 3.8 figure; third-party pages quote GPT-5.6 figures, a different generation.
  Browsing class: 1 eligible model.
- `swe_bench_pro` for `google/gemini-3.8-flash`, `openai/gpt-6-luna`, `openai/gpt-6.1-sol`, `openai/gpt-6.1-terra`:
  not reported at a source I could read, so those four are not eligible for coding (Gemini has one of two
  coding benchmarks). Coding class: 3 eligible models (the three Anthropic ones).
- The Anthropic Haiku 5.5 card quotes the public Terminal-Bench 4.0 leaderboard for GPT-6 Luna (16.4%) and
  GPT-6.1 Sol (58.2%), but both still lack SWE-Bench Pro, so they would not be eligible for coding either;
  not entered (second-hand, the leaderboard itself was not readable: the tbench.ai page rendered no rows).

## Owner spot check (task 2.3) is still owed

The task asks for a human spot check of at least 5 of these figures. An agent read all 9; the owner has
not yet. Until then `verified_at` carries the agent's read date and the owner should open at least five
`source_url`s (suggest: Haiku 5.5 `swe_bench_pro` card 8.2, Sonnet 5.5 and Opus 5.5 `terminal_bench_4_0`,
the Gemini PDF page 4, the Sonar benchmarks page).

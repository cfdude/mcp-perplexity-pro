# Evidence additions (routing-v2, third sourcing pass, 2026-11-19)

Goal: 3 or more eligible shortlist models for `reasoning` and `browsing`. Result: `reasoning` reached (6), `browsing` not (1).

## Figures added (7)

All GPQA Diamond rows are from the Epoch AI Benchmarking Hub (independent leaderboard, CC BY 4.0), read from its
public data download https://epoch.ai/data/benchmark_data.zip, file `gpqa_diamond.csv`, column `mean_score`
(the leaderboard page is https://epoch.ai/benchmarks/gpqa-diamond; it renders client side, so the CSV was the readable form).
Each row's effort is the `_max` suffix of its `Model version`. `as_of` is the row's `Started at` date.

| Model | Benchmark | Score | Epoch row (run id) | as_of |
|---|---|---|---|---|
| `anthropic/claude-sonnet-5-5` | `gpqa_diamond` | 95.58 | `claude-sonnet-5-5_max` (QPk8jbJvo4986sbWtdte6J) | 2026-09-29 |
| `openai/gpt-6.1-sol` | `gpqa_diamond` | 95.39 | `gpt-6.1-sol_max` (LspviLnbeZ82WCngWp6rwR) | 2026-09-29 |
| `openai/gpt-6.1-terra` | `gpqa_diamond` | 94.32 | `gpt-6.1-terra_max` (5Jm2Rvv9sNx7M8nodinFAp) | 2026-10-26 |
| `openai/gpt-6-luna` | `gpqa_diamond` | 90.47 | `gpt-6-luna_max` (7F3QFMAkwnCV62HcvxP96q) | 2026-09-22 |
| `anthropic/claude-haiku-5-5` | `gpqa_diamond` | 89.65 | `claude-haiku-5-5_max` (ZEKWTGJiWFscHimMkiUmec) | 2026-10-09 |
| `openai/gpt-6.1-terra` | `terminal_bench_4_0` | 50.3 | vendor page below | 2026-10-26 (Epoch release date; the page shows none) |

Terminal-Bench source (vendor, read through Tavily because openai.com answers 403 to curl): https://openai.com/index/introducing-gpt-6-1-terra/ ,
quote: "At maximum reasoning effort, GPT‑6.1 Terra solves 50.3% of tasks". This matches the lead the first pass could not verify (50.3).
It does not change coding coverage: Terra still has no SWE-Bench Pro figure.

Corroboration, not entered separately:
- Gemini 3.8 Flash GPQA Diamond 95.3%: vendor-side, in OpenAI's GPT-6 Astra table (https://openai.com/index/gpt-6-astra/, a competitor column, "taken from publicly available reports"); Epoch row `gemini-3.8-flash_high` = 95.39. Agrees with the existing Artificial Analysis figure.
- GPT-6.1 Terra GPQA Diamond (no tools): vendor table in the GPT-6.2 Astra and Sol card, https://deploymentsafety.openai.com/gpt-6-2-astra-sol , Table 2, GPT-6.1 Terra 93.56%. Epoch's 94.32 is entered (independent preferred); the two differ by 0.76.

## Opus 5.5 left out on purpose

Epoch has two `claude-opus-5-5_max` GPQA Diamond rows: 90.59 and a `manual_gpqa_diamond_fallback` row at 94.07. Which one is the model's real figure is a judgment about Epoch's rerun, so none is entered. Reasoning has 6 eligible models without it.

## Not found (browsing)

- `browsecomp` for any shortlist model other than `perplexity/sonar`. OpenAI's own GPT-6 Astra page has a BrowseComp row (Astra 91.5, GPT-5.6 Sol 90.4, Fable 5 87.4, Opus 5 90.8, Gemini 3.8 Flash "-"), none of them shortlist models (Opus 5 is not Opus 5.5; Gemini shows no figure).
- OpenAI GPT-6.1 Sol and Terra announcements, the Sol, Terra and Luna system cards and the GPT-6.2 card: no BrowseComp row. Anthropic pages and system cards for Opus, Sonnet and Haiku 5.5: none. Google Gemini 3.8 Flash evaluation PDF: none. Epoch hub: no BrowseComp dataset. BenchLM, Kaggle (via BenchLeader) and Steel list GPT-5.6 / older models only.
- `swe_bench_pro` for GPT-6.x and Gemini: not published by OpenAI (Astra and Sol/Luna posts use DeepSWE, FrontierCode, Terminal-Bench) nor by Epoch.
- `terminal_bench_4_0` for Luna and Sol: Luna and Sol 6.1 numbers exist only as charts without text in the pages read.

## Access notes

openai.com answers 403 to curl and the fetch tool; Tavily `extract` (advanced) reads it. developers.openai.com and platform.openai.com `.md` pages and deploymentsafety.openai.com are readable directly but carry no capability benchmarks beyond the GPQA row above.

## Coverage after the pass

coding 3 eligible (kept), reasoning 6 (kept), browsing 1 (excluded). Two kept classes, so the gate passes (`coverage.md`).

## Owner spot check (task 2.3)

Open at least five `source_url`s. Easiest: the Epoch GPQA Diamond page (find `claude-sonnet-5-5`, `gpt-6.1-sol`, `gpt-6.1-terra`, `gpt-6-luna`, `claude-haiku-5-5` rows, compare to the table above), the Terra announcement (50.3%), and the older nine from `evidence-verification.md`.

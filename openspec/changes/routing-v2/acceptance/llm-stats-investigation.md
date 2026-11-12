# LLM Stats as a source for routing-v2 evidence (investigation, 2026-11-12)

Method: docs read from https://docs.llm-stats.com (`*.md` pages), OpenAPI read from
https://api.llm-stats.com/stats/openapi.json, then read-only live calls (about 45 data responses
against a 250/day quota). The key was read inside each call and never printed or stored.
Perplexity's `/v1/models` stays the only availability authority; LLM Stats is a metadata layer joined onto it.

## Verdict

LLM Stats cannot source the verified figures routing-v2 needs, for three independent reasons:

1. **Licence.** Community plan forbids redistribution; `data/routing_evidence.json` in a published package is one.
2. **Verification.** 0 of 773 benchmarks and 0 of 2,634 score rows I pulled are flagged verified; 2,541 of them are vendor self-reported.
3. **Coverage.** The shortlist has almost none of the benchmark ids the design names (table below).

It is still useful as a cross-check and a pre-fill (modalities, "what benchmark did the vendor report"), not as the evidence of record.

## 1. Auth, plan, limits (live `GET /v1/account`, costs no quota)

- Base URL `https://api.llm-stats.com/stats/v1`; header `Authorization: Bearer <key>` (keys `sk_ze_...`).
- Live plan: `community`, `plan_version 2`, `daily_quota 250`, `burst_per_minute 50`, `history_months 6`,
  `attribution_required: true`, `redistribution_allowed: false`.
- **Gotcha: live numbers differ from the docs.** Docs (plans-and-quotas) say Community = 500/day and 60/min;
  the live account says 250/day and 50/min. Trust the live account.
- Headers on every response: `x-llm-stats-plan`, `x-quota-limit/-used/-remaining/-reset` (unix, next 00:00 UTC),
  `x-ratelimit-limit/-remaining/-reset`, `x-request-id`. Data routes: `cache-control` per docs; `/account`: `no-store`.
- Quota counts 2xx data responses only; 4xx/5xx/429 free; one response = one unit whatever its size (limit max 200 rows).
- Community does NOT include `GET /v1/changes` or `/v1/snapshots`: both returned 403
  `feature_not_in_plan` ("not included in your plan"); they need Builder ($99/month, 5,000/day, 300/min).
- Opt-in bonus: +250/day per verified integration (max 2) once attribution is observed; "planned" per docs.

## 2. Terms (licence and attribution)

Sources: https://docs.llm-stats.com/api-reference/plans-and-quotas.md and .../attribution.md.
The API terms page (https://llm-stats.com/legal/api-terms) returned 404 to me, so the docs are the only text I read.

- Community: Redistribution "Not permitted"; Attribution "Required for public display".
- "Neither Community nor Builder lets you resell, sublicense, or ship the dataset (or a substantial extract...)".
- Attribution page: "Attribution is not a license"; redistribution "requires a Commercial agreement".
- Public display needs a visible credit naming "LLM Stats" (badge, source link, or plain text
  `Source: LLM Stats (llm-stats.com), retrieved <date>.`), same screen as the data, linking llm-stats.com.
- Redistribution is Commercial only, "per contract" (price not published).

Consequence: a committed `routing_evidence.json` holding LLM Stats scores, shipped on PyPI, is a dataset extract
shipped in a product. Even a handful of rows for 9 models is a judgment call the terms do not bless; I would not ship
it without written permission. Using the numbers privately to decide what to look up elsewhere is fine.

## 3. Coverage for routing-v2 (live)

Id mapping problem, concretely. Ours -> theirs:

| Our id | LLM Stats `model_id` | Rule |
|---|---|---|
| `openai/gpt-6.1-sol` | `gpt-6.1-sol` | strip provider prefix |
| `anthropic/claude-haiku-4-5` | `claude-haiku-4-5-20251001` | their id carries a date suffix |
| `openai/gpt-5.2` | `gpt-5.2-2025-12-11` | date suffix (and `-high`/`-medium` variants also exist as separate ids) |
| `google/gemini-3.1-flash-lite` | `gemini-3.1-flash-lite-preview` | `-preview` suffix |
| `xai/grok-4.20-reasoning` | `grok-4.20-beta-0309-reasoning` | `-beta-0309` infix, not a suffix |
| `perplexity/sonar` | none | LLM Stats has no Perplexity-hosted/Sonar models (`/models/sonar` 404) |
| `perplexity/glm-5.3` | `glm-5.3` (org `zai-org`) | org differs (`perplexity/` is a host, not the maker) |

Benchmark ids also differ: ours `swe_bench_verified`, `terminal_bench_2_1`, `gpqa_diamond`, `browsecomp` ->
theirs `swe-bench-verified`, `terminal-bench-2.1`, `gpqa`, `browsecomp` (hyphens; dots kept).
**`gpqa` is not Diamond:** description says "448 multiple-choice questions" (Diamond is the 198-question subset);
LLM Stats has `gpqa-biology/-chemistry/-physics` but no `gpqa-diamond`. Using `gpqa` for `gpqa_diamond` is a
benchmark substitution, not a mapping.

Scores (LLM Stats scale 0..1; S = `is_self_reported` true; `verified_by_llmstats` false on every row):

| Model (their id) | swe-bench-verified | terminal-bench-2.1 | gpqa | browsecomp | Other coding benchmarks they hold |
|---|---|---|---|---|---|
| openai/gpt-6-luna | none | none | none | none | deepswe-1.1 0.666 S |
| anthropic/claude-haiku-5-5 | none | none | none | none | swe-bench-pro 0.648, terminal-bench-4.0 0.392 (S) |
| perplexity/sonar | no match | no match | no match | no match | - |
| google/gemini-3.8-flash | none | 0.894 S (source: deepmind.google/models/evals-methodology/gemini-3-8-flash/, scored_at 2026-11-11) | none | none | terminal-bench-4.0 0.191, deepswe-1.1 0.737 |
| anthropic/claude-sonnet-5-5 | none | none | none | none | swe-bench-pro 0.813, terminal-bench-4.0 0.706, deepswe-1.1 0.71 (S) |
| openai/gpt-6.1-sol | none | none | none | none | deepswe-1.1 0.7522 S |
| openai/gpt-6.1-terra | none | none | none | none | terminal-bench-4.0 0.503 S |
| anthropic/claude-opus-5-5 | none | none | none | none | swe-bench-pro 0.899, terminal-bench-4.0 0.664, deepswe-1.1 0.742 |
| xai/grok-4.7 | none | none | none | none | terminal-bench-4.0 0.38, deepswe-1.1 0.71 (S) |

Result: of 9 shortlist models x 4 benchmarks = 36 cells, **1 cell is filled** (gemini-3.8-flash on terminal-bench-2.1),
self-reported by Google. The newest models report a newer generation of benchmarks (Terminal-Bench 4.0, SWE-Bench Pro,
DeepSWE) instead of the ids in design.md. No class would have an eligible model under the "every listed benchmark
verified" rule.

Across all 55 Perplexity models (51 matched), models with a score for: swe-bench-verified 14, terminal-bench-2.1 14,
gpqa 26 (pull stopped at 6 pages: 240 of ~265 models, so this is a lower bound), browsecomp 17, terminal-bench-4.0 19,
swe-bench-pro 20, deepswe-1.1 28. Models with both of the `coding` benchmarks as designed: 2.

Field semantics (OpenAPI `ScoreRow`/`BenchmarkScore`): `score`, `normalized_score`, `max_score`, `is_self_reported`,
`verified` / `verified_by_llmstats`, `source_url` (null on 10 of the 183 per-model rows I read), `scored_at` (this is the
ingest timestamp, e.g. 2026-11-11, not the publication date), `rank`. Benchmark objects carry `verified` (false on all
773) and `model_count`. There is no harness field and no independent-vs-vendor field other than `is_self_reported`.

Pagination gotcha: `/v1/scores?benchmark=gpqa` returned `total` 1325 for 240 models; each model repeats 4-5 times
with identical rows (swe-bench-verified: total 372 for 124 models), so full pulls waste 3-5x quota. Fetch by
`/v1/models/{id}` (scores embedded, 1 unit per model) or dedupe client-side.

## 3a. The join from Perplexity's 55 models (`/v1/models` set = baseline's 54 + live `openai/gpt-6.1-terra`)

Rule (family + version normalisation, implemented in the scratchpad script): drop the provider prefix; lower-case; treat
`.` and `-` as equal; ignore a trailing date (`-YYYYMMDD` or `-YYYY-MM-DD`), `-preview`, or `-beta-NNNN`; require the
maker org to match when the Perplexity provider is the maker (for `perplexity/*` hosted open models the maker is
deepseek/zai-org/moonshotai/nvidia, so match by slug only).

- Matched: **51 of 55 (92.7%)**; exact slug 41, normalised 10 (date/preview/beta suffix).
- Unmatched: **4 of 55 (7.3%)**: `perplexity/sonar` (no LLM Stats model), `perplexity/nemotron-3.5-super-120b-a12b`
  (only `nemotron-3.5-super-vl-120b-a12b`, a different model), `xai/grok-4.20-reasoning` and
  `xai/grok-4.20-non-reasoning` (only `grok-4.20-beta-0309-*` snapshots; a strict suffix rule does not match them).
  A fuzzy infix rule would catch the two grok ids, but that is a guess about snapshot identity.
- `grok-4.20-multi-agent` matched only by the same suffix rule onto `grok-4.20-multi-agent-beta-0309`.
- Matched is not the same as scored: of the 51, 36 hold at least one of our four benchmarks, 15 hold none; 2 hold both coding ones.
- Mapping must be an explicit checked-in table (our id -> theirs, with the rule noted), not computed at runtime, because the
  rule has a real false-match risk (e.g. `gpt-5.1` vs `gpt-5.1-high-2025-11-12`).

## 4. Other fields (live, all 444 models listed)

| Field | Finding |
|---|---|
| Price | `providers[].input_price_per_m/output_price_per_m` USD per million tokens; present for 47 of 51 matched models. Redundant with Perplexity's own `/v1/models` pricing (our matrix already holds it). Example mismatch risk: LLM Stats lists the maker's price, Perplexity's may differ. |
| Context window | `context_window` is **null for all 444 models**; unusable. |
| Modalities | `modalities` array, values seen only `text`, `image`, `audio`, `video`. Present for the 51 matched: text+image 35, text+image+audio+video 11, text-only 3, text+image+video 2. Empty for 120 of 444 models overall. **No `document`/PDF value exists.** `inference.supports_vision` is false for every model I looked at, even image-capable ones, so it is not usable. |
| Availability/deprecation | `providers[].status` is `active` for all 444; no deprecation/retirement/sunset date field in OpenAPI, and the docs contain no such word. LLM Stats does not tell us a model is going away. |
| New-model feed | `GET /v1/updates?days=N` (Community OK, 200) lists models added in a window: `id, name, organization, modalities, release_date, added_at` (e.g. `claude-mythos-5-2`, `claude-fable-5-2` added 2026-11-09). Useful as a "new model exists" hint only. |
| Change feed | `/v1/changes` (cursor creates/updates/removals) exists but is **403 on Community**; Builder only. |
| History | `/v1/models/{id}/history` (score, ranking, pricing, metadata) 6-month window on Community; not called. |
| Other | `release_date`, `knowledge_cutoff`, `license`, `open_weight`, `top_scores` by category, source links. |
| MCP | Hosted read-only MCP at `https://mcp.llm-stats.com/mcp` (OAuth or key); shares the same org quota; one workflow tool `compare-run` calls their paid gateway. Nothing we need. |

## 5. Recommendation (evidence only)

**Do not source `routing_evidence.json` from LLM Stats.** Keep routing-v2's evidence source as the vendor/independent
leaderboard pages the design already requires each score to cite with a `source_url`, `harness` and `verified_at`.

If LLM Stats is used at all, use it offline, by the owner, as a lead generator and cross-check:

- A script run by the owner (never at server runtime, never by users, no key in the package) pulls `/v1/models/{id}` for the
  shortlist (9-10 units, plus 1 `/benchmarks`), prints a table of "benchmark the vendor reported" with the linked `source_url`.
  Whole job: about 12 data responses of a 250/day quota. A full model-list pull is 3 units; avoid full `/scores` pulls (duplicated rows).
- The output is a worksheet, not a shipped file: a human opens each `source_url`, confirms the figure and harness, and only
  then writes `verified_at` in our file. That keeps the "verified" rule honest and keeps LLM Stats data out of the package.
- Record in the script run: date, response `x-request-id`s, and the benchmark/model ids used. There is no snapshot checksum
  on Community (snapshots are Builder). A dated local copy of the JSON in `acceptance/` is the only pin; do not commit LLM
  Stats rows to a public repo, per section 2.
- Attribution if any LLM Stats-derived number ever appears in docs: plain text `Source: LLM Stats (llm-stats.com), retrieved <date>.`
  next to the data. Needed even for Community internal-then-published use.
- Runtime lookups: no. They add a key requirement, latency, a quota that Community cuts to 250/day, and a licence problem.

Mapping to our "verified" rule: LLM Stats `is_self_reported: true` is our `basis: vendor`; `false` could be `independent`
(only 93 of 2,634 rows were false, none verified). `verified` / `verified_by_llmstats` is false everywhere, so it can never
set our `verified_at`. At best an LLM Stats row yields `verified_at: null` (to be sourced), which selection ignores.

## 6. Unmatched-model rule (proposed)

A Perplexity model with no LLM Stats match, or a match with no score for a benchmark the class lists, has no verified
score and is **not router-eligible** for that class (the existing "unverified is ignored" rule, routing-evidence
requirement "Every score carries its source and date"). It stays callable by explicit `model=`. The 4 unmatched ids
(`sonar`, `nemotron-3.5-super-120b-a12b`, `grok-4.20-reasoning`, `grok-4.20-non-reasoning`) are ineligible by default.
`perplexity/sonar` is the fallback-adjacent case: it needs its own sourced figures or stays outside the shortlist.

## 7. Does LLM Stats help the media-inputs matrix?

Cross-check yes, pre-fill partly, replace no. Modalities give image/audio/video for ~all matched models, so they can
flag a probe result that disagrees (our matrix says a model refuses images while LLM Stats lists `image`). There is no
document/PDF modality, 120 of 444 models have empty modalities, `supports_vision` is false even for image models, and it
reflects the maker's model, not what Perplexity's hosted route accepts (a `perplexity/*` open-weight host can differ).
So the live probe remains authoritative; use LLM Stats only as an advisory hint, never as `accepts() == yes`.

## Files

Raw responses (no key) in the session scratchpad:
`/private/tmp/claude-501/-Users-rsherman-Servers-mcp-perplexity-pro/0dc2ae42-68b1-4a59-bd08-52a41ae14168/scratchpad/ls/`
(`allmodels.jsonl`, `b.json`, `gm_*.json`, `sc_*.jsonl`, `match.json`, `match.py`, `cov2.py`).

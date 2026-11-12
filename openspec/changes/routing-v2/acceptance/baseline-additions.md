# Baseline additions (routing-v2 task 2.5)

`src/mcp_perplexity_pro/data/model_matrix_baseline.json` holds the 54 models of the 2026-10-17
sweep and, since 2026-11-11, one entry added by hand. The baseline-regeneration script of
`media-inputs` task 2.1 (`openspec/changes/media-inputs/acceptance/scripts/`) rebuilds the file from
the sweep and does NOT reproduce a hand-added entry, so a later regeneration MUST re-add the
entries below (and keep the file's format: `json.dumps(doc, indent=1) + "\n"`, models sorted by id).

| Model id | Added | Price source | Efforts | Inputs |
|---|---|---|---|---|
| `openai/gpt-6.1-terra` | 2026-11-11 | `GET /v1/models` of 2026-11-11, capture `tests/fixtures/models_2026-11-11.json` (input 1, output 5, cache read 0.05, cache write 1.25 USD per 1M) | probed live 2026-11-11 (control plus `minimal` to `max`, all 200 and `completed`, about 0.0005 USD in all), `source` `baseline`, `probed_at` 2026-11-11T00:00:00Z | unanswered: `source` `unprobed`, nothing attempted (the 2026-10-30 sweep did not cover it; the scheduled refresh probes it) |

Why: owner decision 2026-11-11 replaced `xai/grok-4.7` with `openai/gpt-6.1-terra` on the router
shortlist (design "Shortlist proposal"). Its efforts were probed rather than left unprobed so that
the matrix tests that count unprobed models keep their meaning and the router can clip a level
for it from the first call.

Side facts of the same capture (not added): the 2026-11-11 list also holds
`anthropic/claude-fable-5-2` and `google/gemini-4-carbon` (not in the baseline, never routed: no
evidence, not shortlisted) and no longer lists `perplexity/nemotron-3-ultra-550b-a55b`, which the
baseline still holds as `available` until a refresh marks it `removed`.

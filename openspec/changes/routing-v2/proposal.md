# Proposal

## Why

Dynamic mode (`routing-rules-v1`, `routing-decisions-classifier`) picks one of three tiers and maps
each tier to a fixed preset or a configured model. That answers "how hard is this prompt" and never
"which model is good at this kind of prompt, at what price". The 2026-10-15 research
(`docs/research/2026-10-15-model-benchmarks/`, a draft that nobody has verified) shows 54 live
models whose prices differ by a factor of 100 and whose published scores often sit within a few
points of each other, so the cheapest adequate model is a different model for coding, reasoning and
browsing prompts. The matrix (`model-matrix`) already holds prices, availability and accepted effort
levels, so the one missing input is benchmark evidence. Rob decided on 2026-10-29 not to publish the
matrix or dynamic routing (2.1.0 and 2.2.0 are unpublished) until this router replaces them. On
2026-11-11 he made the proof a condition of merging this change: routing must deliver value, not bloat (no added
delay, no added tokens, real usage savings from cheaper models on lighter work), and "if we can't prove those
things, we keep it in a branch and do not merge". The proof is an in-branch evaluation (`routing-evaluation`).

## What Changes

- A versioned, dated evidence file shipped in the package (`routing_evidence.json`, like the matrix
  baseline): a curated shortlist of about eight models, the benchmarks per task class, and one score
  per model and benchmark with its source URL, as-of date and independent-or-vendor label. A score
  without a source and date is refused at load. This change ships the schema, the loader and the
  procedure, not the figures: every figure is TO BE SOURCED and verified live (tasks 2.x) before the
  router may be switched on.
- A model-gone refresh (design D17): when a call to a server-chosen model fails with the API's answer that
  the model is no longer served (the one classifier `matrix.model_not_served`, owned by `media-inputs`), the
  server refreshes the catalog from the API's own `/v1/models` (single-flight, at most once per 5 minutes per
  process, no probes, no documentation scraping), skips the retired id at selection time, and retries the call
  ONCE on the best same-family shortlist model, else the chain fallback; the result's `routing.reason` says
  `model_retired:<id>`. An explicit `model`, a pin and a mode model that are gone are reported with the live
  same-family candidates named, never replaced.
- A merge-blocking, pre-registered evaluation (design D18, capability `routing-evaluation`): a fixed labeled
  set (at least 12 coding, 12 reasoning and 12 browsing prompts, pinned by hash), thresholds written before
  any run (decision p95 under 5 ms; no added network call; median added wall time under 50 ms; no added input
  tokens and a `routing` object of at most 400 bytes; cost at most 0.75 of an always-strongest baseline and at
  most 4.0 of an always-cheapest one; quality within 0.05 overall and 0.10 per class of the strongest model),
  live spend under 5 USD, and a report `acceptance/evaluation.md` with a PASS or FAIL line per threshold.
  The shipped evidence has no scores, so the router cannot pass until figures are sourced and verified
  (an unverified run is INVALID); on FAIL the routed selection stays unmerged and `media-inputs` ships alone.
- A deterministic, pure selector picks `(model, effort)` for a nameless ask, chat send or research
  run: a task class from the prompt (coding, reasoning or browsing), the eligible shortlist models
  (available in the matrix, scored on the class, and answering `yes` to the matrix's `accepts` for the required input kinds), the best
  score, every model within a named margin (3 points proposed) of it, and the cheapest of those by
  the matrix price.
- The effort comes from the tier the classifier already computes, capped per tool (ask and chat stay
  within `low` and `medium`; research may reach `high`), and is clipped to the levels the model
  accepts. For ask and chat the tiers `standard` and `complex` therefore differ only in what is
  recorded.
- A fallback chain when no model is eligible: `openai/gpt-6-luna` at `low`, then the tier's
  documented preset (text only, search on); a lower accepted effort of the chosen model is applied
  before any fallback. The earlier `xhigh` rung is dropped because no call can reach it.
- Explicit `model`, `depth` and `tier` keep working exactly as today (an explicit model wins and is
  never rewritten). `dynamic` mode becomes the router; `standard` and `custom` are unchanged;
  `PERPLEXITY_TIER_*` in `dynamic` mode pin a tier's model instead of replacing a preset.
- The router reaches the API as `model` plus `reasoning.effort` (the shape the matrix probe already
  sends), so a routed call carries the explicit-model request shape; the result's `routing` object
  gains `effort`, and `selected_by` gains `router` and `fallback`.
- A chat follow-up holds the higher of its classified tier and the previous turn's tier, and keeps the
  previous turn's `routed_model` when it is still available and the matrix says `yes` for the required kinds, unless an
  explicit selector changes it; the tier (a named one included) is
  stored per assistant message beside `routed_model`, the requested id the hold uses (the stored `model`
  is the API-reported id and can differ). Migration `0006` adds `chat_messages.tier`,
  `chat_messages.routed_model` and `research_jobs.effort` (all nullable; the downgrade uses `DROP
  COLUMN` so it cannot cascade into stored vectors).
- `perplexity_research.depth` becomes optional with no default (an omitted depth is no longer the
  same as an explicit `medium`); in `dynamic` mode an omitted depth is routed, and a routed job stores
  depth `routed`, its level in `research_jobs.effort` and a null preset in usage events; the jobs
  tool and `JobInfo` show `routed` with the model and effort. When no model is eligible, research
  falls back to the tier's preset, never to `gpt-6-luna`.
- A named `tier` in `dynamic` mode skips the tier classifier but the offline rules still give the task
  class; `selected_by` is `tier`.
- One hook with `media-inputs`, which owns the modality facts (the matrix `inputs` record, `accepts`,
  `models_accepting`, `preset_accepts`) and the attachment gate: the selector takes `required_input`, a
  set of `image` and `document` (empty means text only), and substitutes only models the matrix
  answers `yes` for. This change only selects; the gate on the final route is `media-inputs`'.
- Out of scope, recorded: the decider default and the classifier default (`rules`) stay, because
  `pplx-decider-v1.2` and `flash-v1.2` answered differently from `v1.1` and need the
  `routing-eval-tuning` evaluation; escalation (`routing-escalation`); a router backend
  (`routing-router-api-backend`); any savings figure in a document before the evaluation report passes (after
  it passes, documents may quote the measured figures); `xhigh` automation (owner, 2026-11-11); adding
  `xai/grok-4.7` to the shortlist (a later round); media inputs themselves.
- Owner decisions of 2026-11-11 (design D2, D6, open questions 2, 3 and 8): the benchmark mapping and the
  3-point margin as drafted; the shortlist swaps `xai/grok-4.7` for `openai/gpt-6.1-terra` (live in
  `/v1/models` on 2026-11-11, needs a baseline entry, task 2.5); the last resort for a task the chain
  cannot place is the request's own preset model; `anthropic/claude-opus-5-5` stays allowed.

## Capabilities

### New Capabilities
- `routing-evidence`: the evidence file, the shortlist, the selection algorithm, effort choice, the fallback chain, the modality hook and the retired-model retry.
- `routing-evaluation`: the pre-registered, merge-blocking evaluation (thresholds, labeled set, harness, budget, report, honest fallback rule, the split with `media-inputs`).

### Modified Capabilities
- `routing-config`: `dynamic` mode runs the router; tiers become effort tiers; tier variables pin models; "The tier argument", "The classifier field can be decisions", "Usage records the resolved model" (the "routing adds no migration" clause goes), the `routing` object, the instructions text, the follow-up hold and its storage; two requirements removed.
- `routing-rules`: a task class and its two fixed vocabularies, offline.
- `routing-decisions-classifier`: the classifier runs for `search` false calls, never for research, and a named tier has no classifier.
- `agent-ask`: a routed model call may carry `reasoning.effort`; the depth rule, "Ask tool" and "Agent requests name the preset as effort" (the research scenario).
- `agent-chat`: "Chat tool" (description sentence), "Chat storage" (the new column), "Send starts a chat" (dynamic wording) and the stored tier.
- `agent-research`: "Research tool" (optional `depth`), "The model is known only from a finished run", "Job records", "Recording follows the recorder contract", "Submit that returns another status" (preset null for a routed submit), routed research and its job columns.
- `server-runtime`: "Dynamic mode configuration" (pins; `PERPLEXITY_MODEL` ignored).
- `model-matrix`: the forced, rate-limited, single-flight refresh after a retired model (added requirement; `media-inputs` owns the rest of the capability and the `model_not_served` predicate).
- `help-tool`: "The index and routing topic describe dynamic mode".
- `model-catalog`: the `perplexity_models` routing section reports the router and its evidence; the held listing is readable without a fetch.

## Impact

- Code (at apply time): new `routing_select.py` (pure) and `routing_evidence.py` (loader and
  `EvidenceState`), edits to `routing.py`, `rules.py`, `settings.py`, `agent.py` (`reasoning` in a
  model request; the preset of a routed job), `server.py` (`AppContext.evidence`), `__main__.py`
  (startup warnings, readers of the removed tier table), `command.py` (research `--depth` default),
  `tools/{ask,chat,research,models,jobs}.py` (research submit preset at `research.py` lines 158, 183 and 186), `storage/chats.py` (`AssistantTurn`, `last_route`), `pyproject`/packaging test for the data file, `routing_decisions.py` (`wants_decider`), `help_text.py`, `matrix_refresh.py` (`refresh_now`, the retirement rate limit), `catalog.py` (the held listing without a fetch), `routing_select.py` (family key, tombstones, exclusion), `agent.py` and the three tools (the single retry and its hint),
  `storage` (migration `0006`, models), data file
  `src/mcp_perplexity_pro/data/routing_evidence.json`; tests (`tests/test_routing.py`,
  `tests/test_routing_dynamic_tools.py`, `tests/test_chats_migration.py:214` and `tests/test_jobs_migration.py:249`, the ORM-against-schema
  tests that the new columns break, `tests/test_research_tool.py:322`, the research schema default)
  and fixtures; README, CHANGELOG, CLAUDE.md.
- Migration `0006`: `chat_messages.tier`, `chat_messages.routed_model` and `research_jobs.effort`, nullable, reversible; the downgrade
  needs SQLite 3.35.0, already required by `RETURNING` in `storage/embeddings.py`.
- Tools-list size: the cap 59779 never rises. This change's growth targets are 650, 790 and 790 bytes over
  57735, 58021 and 58255 (default, dynamic, dynamic with Decisions; design D14 budgets each field); task
  6.2 records the figures, 6.3 trims at least 450 bytes in other tools' descriptions, and 6.4 installs the
  FINAL per-server ceilings from the combined table that media 3.3 writes.
- Live work: a request-shape probe (a model with `reasoning.effort` and the web search tool, in
  the background, for research), a probe of what the API answers for a retired model id, source
  verification of every evidence figure, and the in-branch evaluation (tasks 7.2 to 7.7, under 5 USD
  in total) whose report decides the merge.
- Tests and harness: `tests/routing_eval/` (thresholds, microbenchmarks, paired overhead, three-arm live
  runner, judge), the extended `tests/fixtures/routing_prompts.json`, `acceptance/evaluation.md`.
- Boundary with `media-inputs` (applied in parallel): this change owns selection (evidence, eligibility,
  effort, fallbacks, the hold rule); `media-inputs` owns the modality facts in the matrix, the
  attachment parameters, the refusal wording and the gate on the final route (explicit model, pin,
  tier model and default route; a held model is kept only when the matrix answers `yes`, and the router substitutes only `yes` models). CANONICAL APPLY ORDER: (1) media 1.1, 1.2, 1.3, 2.1, 2.2; (2) routing-v2 groups 0-4 and 5.1-5.3; (3) routing-v2 5.4, 5.5, 5.6, 6.1, 6.2, then 6.3; (4) media 1.4, 1.5, 2.3, 2.4, 3.1, 3.2, 4.1, 4.2, then 3.3; (5) routing-v2 6.4; (6) routing-v2 7.1 to 7.7, the in-branch evaluation (7.8 only if the evaluation fails); (7) docs for both (routing-v2 9.1 makes the single CLAUDE.md tools-list figures edit, only after 7.6 reports); (8) routing-v2 9.3, the merge gate, then the archive 9.4. A stub `matrix.accepts` answering `unknown` is the fallback if that order is impossible. If the evaluation fails, task 7.8 unwinds the routed selection and `media-inputs` ships alone (design D18 lists exactly what it took from this change: nothing from migration `0006`, the `required_input` call into `resolve` and the held-model and router-substitution wording).

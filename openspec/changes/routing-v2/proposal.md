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
  set (at least 15 main and 5 held-out prompts per class, at least half machine-checkable, split frozen
  early, pinned by hash), four arms (routed; the named model `anthropic/claude-opus-5-5`; the cheapest
  shortlist model; the STATUS QUO route of commit d2798cd), and thresholds written before any run: decision
  p95 under 5 ms and no added network call; median added wall time under 50 ms; no added input tokens and a
  `routing` object of at most 400 bytes; cost at most 0.75 of the strongest arm, at most 4.0 of the cheapest
  and at most 1.00 of the status quo; quality by a paired non-inferiority test (95 percent lower bound at
  least -0.10 overall, -0.15 per class, -0.10 against the status quo) with a blind, label-free judge
  validated by Cohen's kappa. Live work stays under 10 USD in all, after a 6-prompt pilot; the code is
  frozen with Gate 2 recorded before the evaluation, and a CI test refuses the merge without a fresh
  `MERGE ALLOWED` report. The shipped evidence has no scores, so the router cannot pass until figures are
  sourced and verified (an unverified run is INVALID); on FAIL the routed selection stays unmerged and
  `media-inputs` can merge alone (nothing is tagged without an owner decision).
- A deterministic, pure selector picks `(model, effort)` for a nameless ask or chat send: a task class from the prompt (coding, reasoning or browsing), the eligible shortlist models
  (available in the matrix, scored on the class, and answering `yes` to the matrix's `accepts` for the required input kinds), the best
  score, every model within a named margin (3 points proposed) of it, and the cheapest of those by
  the matrix price.
- The effort comes from the tier the classifier already computes, capped at `medium` (a call has a 120 s
  timeout; `high` and `xhigh` are never automatic), and is clipped to the levels the model
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
  `chat_messages.routed_model` (both nullable; the downgrade uses `DROP
  COLUMN` so it cannot cascade into stored vectors).
- Research is unchanged (owner decision 2026-11-12, scope down): in `dynamic` mode `perplexity_research` keeps its
  preset, with no routed depth, no stored effort and no optional `depth`; routed research selection is deferred
  to the registered epic `routing-research`, and the evaluation claim covers `ask` and chat send only.
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
- `routing-decisions-classifier`: the classifier runs for `search` false calls, and a named tier has no classifier.
- `agent-ask`: a routed model call may carry `reasoning.effort`; the depth rule, "Ask tool" and "Agent requests name the preset as effort".
- `agent-chat`: "Chat tool" (description sentence), "Chat storage" (the new column), "Send starts a chat" (dynamic wording) and the stored tier.
- `server-runtime`: "Dynamic mode configuration" (pins; `PERPLEXITY_MODEL` ignored).
- `model-matrix`: the forced, rate-limited, single-flight refresh after a retired model (added requirement; `media-inputs` owns the rest of the capability and the `model_not_served` predicate).
- `help-tool`: "The index and routing topic describe dynamic mode".
- `model-catalog`: the `perplexity_models` routing section reports the router and its evidence; the held listing is readable without a fetch.

## Impact

- Code (at apply time): new `routing_select.py` (pure) and `routing_evidence.py` (loader and
  `EvidenceState`), edits to `routing.py`, `rules.py`, `settings.py`, `agent.py` (`reasoning` in a
  model request), `server.py` (`AppContext.evidence`), `__main__.py`
  (startup warnings, readers of the removed tier table), `tools/{ask,chat,models}.py`, `storage/chats.py` (`AssistantTurn`, `last_route`), `pyproject`/packaging test for the data file, `routing_decisions.py` (`wants_decider`), `help_text.py`, `matrix_refresh.py` (`refresh_now`, the retirement rate limit), `catalog.py` (the held listing without a fetch), `routing_select.py` (family key, tombstones, exclusion), `costed.py` and `agent.py` (an optional `model=` so a failed call's usage event names the model), the ask and chat tools (the single retry and its hint),
  `storage` (migration `0006`, models), data file
  `src/mcp_perplexity_pro/data/routing_evidence.json`; tests (`tests/test_routing.py`,
  `tests/test_routing_dynamic_tools.py`, `tests/test_chats_migration.py:214`, the ORM-against-schema
  test that the new columns break)
  and fixtures; README, CHANGELOG, CLAUDE.md.
- Migration `0006`: `chat_messages.tier` and `chat_messages.routed_model`, nullable, reversible; the downgrade
  needs SQLite 3.35.0, already required by `RETURNING` in `storage/embeddings.py`.
- Tools-list size: the cap 59779 never rises. This change's growth targets are 300, 440 and 440 bytes over
  57735, 58021 and 58255 (default, dynamic, dynamic with Decisions; design D14 budgets each field); task
  6.2 records the figures, 6.3 trims at least 450 bytes in other tools' descriptions, and 6.4 installs the
  FINAL per-server ceilings from the combined table that media 3.3 writes.
- Live work: a request-shape probe (a model with `reasoning.effort` and the web search tool), a probe of what the API answers for a retired model id, source
  verification of every evidence figure, and the in-branch evaluation (pilot 7.1b and tasks 7.2 to 7.7,
  under 10 USD for all live work of the branch) whose report decides the merge.
- Tests and harness: `tests/routing_eval/` (thresholds, microbenchmarks, paired overhead, three-arm live
  runner, judge), the extended `tests/fixtures/routing_prompts.json`, `acceptance/evaluation.md`.
- Boundary with `media-inputs` (applied in parallel): this change owns selection (evidence, eligibility,
  effort, fallbacks, the hold rule); `media-inputs` owns the modality facts in the matrix, the
  attachment parameters, the refusal wording and the gate on the final route (explicit model, pin,
  tier model and default route; a held model is kept only when the matrix answers `yes`, and the router substitutes only `yes` models). CANONICAL APPLY ORDER: (0) first the worktree (routing-v2 0.4), then routing-v2 0.1 and media 0.1, 0.3, 0.4, 0.5 (media 0.2 with the first commit of its scripts, and only if `pyproject.toml` lacks the exclude); (1) routing-v2 1.1 and 1.3 to 1.5 and media 1.1, 1.2, 1.3, 2.1, 2.2; (2) routing-v2 groups 2, 3 and 4, then 5.1 to 5.3a; (3) routing-v2 5.4, 5.5, 5.6, 6.1, 6.2, then 6.3; (4) media 1.4, 1.5, 2.3, 2.4, 3.1, 3.2, 4.1, 4.2, then 3.3; (5) routing-v2 6.4, 7.1 and 7.4 (with its dry run of T1 to T3), and media 5.1; (6) the CODE FREEZE: routing-v2 8.1, 8.2, 8.3 and 8.5 and media 6.1 to 6.5 over ONE head (both Gate 2 verdicts recorded at it), then routing-v2 7.1a, the offline unwind rehearsal; (7) routing-v2 7.1b, 7.2, 7.3 and 7.5 to 7.7, the in-branch evaluation (7.8 only if it fails), any `src/` commit after 7.6 requiring a new numbered run; (8) docs for both (routing-v2 9.1 makes the single CLAUDE.md tools-list figures edit, then routing-v2 8.4 and 8.6; media 7.1), then the docs-only reviews routing-v2 9.2 and media 7.2; (9) routing-v2 9.3, the merge gate, then 9.4, the worktree cleanup, and the archives (routing-v2 9.5, media 7.3). A stub `matrix.accepts` answering `unknown` is the fallback if that order is impossible. If the evaluation fails, task 7.8 unwinds the routed selection and `media-inputs` ships alone (design D18 lists exactly what it took from this change: nothing from migration `0006`, the `required_input` call into `resolve` and the held-model and router-substitution wording).

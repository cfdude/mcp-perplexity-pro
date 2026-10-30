# Design

## Context

Dynamic mode today: `rules.classify(text)` (or the Decisions classifier) returns a tier, and
`routing.dynamic_route` maps the tier to preset `fast`, `PERPLEXITY_MODEL` or preset `medium`
(`settings.dynamic_target`). The matrix (`matrix.py`, `matrix_refresh.py`, baseline
`data/model_matrix_baseline.json`, 54 models) holds, per model, `status`, per-million prices and the
accepted `reasoning.effort` levels. The Agent API takes a preset as the body field `effort` (a bundle
of model and tools) or a `model` (plus our web search tool and a step budget of 3, plus, new here,
`reasoning.effort`, the shape `client.probe_effort` already sends). Vocabulary: a *task class* is
one of `coding`, `reasoning`, `browsing`; a *tier* is `light`, `standard` or `complex` (how hard the
prompt looks); a *level* is one effort value of the matrix; a *shortlist* is the models the router
may choose; *evidence* is the benchmark data file.

`docs/research/2026-10-15-model-benchmarks/` is an unverified Perplexity Research draft. It already
shows why the data cannot be trusted unread: some figures look implausible (for one model a
SWE-bench Verified score above 95 percent), vendors report different coding benchmarks, and one
benchmark appears in several versions (Terminal-Bench 2.1 and 4.0). Nothing from it is copied into
this change.

## Goals / Non-Goals

**Goals:**
- Pick `(model, effort)` per prompt from dated, sourced evidence and live price, deterministically
  and offline (pure, no network, no clock, no randomness).
- Stay correct when the catalog changes (a model removed, a price moved, an effort refused, a new
  model listed): no hand edit is needed for the router to stay safe.
- Keep every explicit selector exactly as it is.

**Non-Goals:**
- No savings or quality claim (`routing-eval-tuning` is the only place one is made); no escalation
  or retry one tier up; no router API backend; no change to the classifier defaults; no media inputs.
- No invented benchmark number: this change ships the schema and the procedure, not the figures.

## Decisions

**D1. The evidence is a packaged, dated data file, read like the matrix baseline.**
`src/mcp_perplexity_pro/data/routing_evidence.json`, read with `importlib.resources`; a file of the
same name in `PERPLEXITY_DATA_DIR` (hand-edited by the owner, never written by the server) takes
precedence, and a missing, corrupt, invalid or newer-version file falls back to the packaged one with
one warning (the matrix loader's rules, without the rename-aside because the server never writes it).
Shape (version 1); a benchmark's version is part of its id, so identity is the id:

```json
{
  "version": 1,
  "as_of": "YYYY-MM-DD",
  "task_classes": {"coding": {"benchmarks": ["swe_bench_verified", "terminal_bench_2_1"]},
                   "reasoning": {"benchmarks": ["gpqa_diamond"]},
                   "browsing": {"benchmarks": ["browsecomp"]}},
  "benchmarks": {"terminal_bench_2_1": {"name": "Terminal-Bench 2.1"}},
  "shortlist": ["<model id>", "..."],
  "fallbacks": {"default": {"model": "openai/gpt-6-luna", "effort": "low"}},
  "models": {"<model id>": {
      "scores": {"terminal_bench_2_1": {"score": 0.0, "source_url": "https://...", "as_of": "YYYY-MM-DD",
                                        "basis": "independent", "harness": "text or null",
                                        "verified_at": "YYYY-MM-DD or null"}}}}
}
```

Loader rules: a score is a number from 0 to 100 with `source_url` (https), `as_of` and `basis`; a
missing field (`harness` included: text or null) is an invalid file (never a silent skip: an unsourced
number is how a figure gets invented); every benchmark id a class lists must exist in `benchmarks`; `verified_at` may not precede the score's `as_of` or be after the load date. A score with
`verified_at` null is TO BE SOURCED: kept, ignored by selection. Every shortlist id and
`fallbacks.default.model` must have an entry in `models`. An empty `scores` object is valid and is
the shipped state: the file ships with the schema, the shortlist and no scores, so until tasks 2.2
and 2.3 add and verify figures every nameless call falls back.

**Loading and startup warnings.** The evidence is held by an `EvidenceState` on `AppContext` (the
matrix's `MatrixState` pattern: lazy `snapshot()`, no read at `build_server`, so `perplexity-pro
help` and the schema builder touch no file). The two startup warnings (`as_of` more than 90 days
old; no verified score) are emitted by `__main__.bootstrap` when it serves (`serving=True`) in
`dynamic` mode only, by reading the snapshot once; `standard` and `custom` never read the file, and a
one-shot command warns nothing. `server.py` gains the holder and
`__main__.py` the warning call; both are in the call-site sweep.

**D2. The benchmark-to-task mapping is data, drafted for the owner to edit.** The table lives in
`task_classes` of the evidence file; editing it needs no code change. A class's score for a model is
the arithmetic mean of that class's benchmark scores, and a model that lacks a verified score for any
benchmark of the class is not eligible for the class.

| Task class | Benchmark ids (version inside the id) | Combined as | Chosen by (rules, in this order) |
|---|---|---|---|
| `coding` | `swe_bench_verified`, `terminal_bench_2_1` | mean | a fenced block or a phrase of the coding vocabulary |
| `reasoning` | `gpqa_diamond` | the score | a word of the reasoning vocabulary |
| `browsing` (also the default) | `browsecomp` | the score | everything else, because every routed call is web-grounded |

The two vocabularies are listed in full in the `routing-rules` delta (the code reads them from
`rules.py`, pinned by `tests/test_rules.py` and the labeled set). Generic words (`function`, `bug`)
and language names are excluded on purpose: `What is the latest stable Python release?` must stay a
light `browsing` lookup. Draft margin: **3 points** (D4). Owner edits: benchmark ids, class
membership, the vocabularies.

**D3. Selection algorithm (pure; `routing_select.select(...)`).** Inputs, all passed as arguments:
the task class, the tier, the tool (`ask`, `chat`, `research`), the evidence, a matrix snapshot
(`matrix.Matrix`), `required_input` (a frozenset drawn from `{"image", "document"}`, default empty = text only), the margin and
`search`. Steps:
1. Eligible = shortlist models that are `available` in the matrix, have both prices non-null, answer
   `yes` to `matrix.accepts(model, required_input)` (always true for an empty set; `no`, `unknown`
   and unprobed are never substituted), and have a verified score for every benchmark of the class.
2. If Eligible is empty, take the fallback chain (D6).
3. `best` = the highest class score. Contenders = eligible models with `score >= best - margin`,
   compared as `Decimal` built from the JSON text (so `80.3 - 3` equals `77.3`, which floats get wrong).
4. Winner = the contender with the lowest blended price (D4); ties go to the higher score, then to
   the lexicographically smaller id, so the result never depends on dict or set order.
5. Effort (D5) for the winner; the result is `(model, effort, reason)`.

**D4. Price tie-break.** Blended price = `(3 * input + 1 * output) / 4` per million tokens, from
the matrix (`PRICE_WEIGHTS = (3, 1)`, named, because a grounded answer reads more than it writes;
tuned by the evaluation, not by guess). `MARGIN_POINTS = 3.0` is a named constant that
`PERPLEXITY_ROUTER_MARGIN` (0 to 20) overrides; 0 means "the best score always wins". A model whose
price is unknown is not eligible. Cache prices are ignored.

**D5. Effort.** The tier gives a target level: `light` is `low`, `standard` is `medium`, `complex`
is `medium` for ask and chat (their cap: a call has `PERPLEXITY_AGENT_READ_TIMEOUT`, 120 s, and
`high` can run longer) and `high` for research (`RESEARCH_AUTO_MAX = high`; `xhigh` is reachable only
by naming `depth` `xhigh`). The level sent is the highest accepted level not above the target, else
the lowest accepted level, else no `reasoning` (no level accepted, never probed, or the model absent
from the matrix, which includes a pin on an unknown model). The tier never changes which model wins:
the class does. Consequence, stated plainly: for ask and chat the tiers `standard` and `complex`
send the same effort and the same model; they differ only in what is recorded and in the chat hold
(D12). `light` differs by `low`. Research is where `complex` costs more.

**D6. Fallback chain (every rung checked against the matrix before use).** Ask and chat: (a) the
chosen model at the lowest accepted level when none is at or below the target (inside D5); (b)
`fallbacks.default` (`openai/gpt-6-luna`, `low`) when `available` and `accepts(...) == yes`; its `low`
is clipped like any level (the highest accepted level not above `low`, else no `reasoning`; not the
lowest accepted, because the rung exists to be cheap); (c) the documented preset of the tier (`fast`,
`low`, `medium`), allowed only when `search` is not false and, when media is required, only when
`matrix.preset_accepts(preset, kinds) == yes`, otherwise not allowed.
Research skips (b) and goes straight to the tier's preset (`medium` for `light` and `standard`,
`high` for `complex`), so a deep run is never silently replaced by a cheap model. When `search` is
false or media is required and no model rung exists the call fails with `invalid_request`. `selected_by` is
`fallback` and the reason names the rung. The earlier `by_target_effort` rung (`xhigh` to
`openai/gpt-6.1-sol`) is removed: `xhigh` is never an automatic target and an explicit `depth` `xhigh`
is a preset sent verbatim, so no call could reach that rung (open question 2). Note for the owner:
`catalog.PRESETS` (2026-10-29) maps `fast`, `low`, `medium` to `openai/gpt-6-luna`, while the research
notes say the docs name `gpt-5.6-luna`; rung (c) sends a preset name, so the discrepancy cannot
misroute, and task 1.3 re-reads the documentation.

**D7. Modality: one source of truth, owned by `media-inputs`.** The model matrix is the single
source of modality facts: `media-inputs` adds a per-model `inputs` record and the pure functions
`matrix.accepts(model, kinds) -> yes|no|unknown`, `matrix.models_accepting(kinds)` and
`matrix.preset_accepts(preset, kinds) -> yes|no|unknown`. This change therefore carries no
`input_modalities` in the evidence file; text is implicit. `routing.resolve(..., required_input=
frozenset())` forwards the kinds to `select`, which treats only `yes` as eligible (so `unknown` or
unprobed models are never substituted) and checks the fallback model and the preset rung through the
same functions; when nothing satisfies the set it raises `invalid_request` naming the kinds.
`select` only SELECTS. The one gate that decides whether the FINAL route may carry the attachments is
`media-attachments`' `accepts` check on an explicit model, a pin, a tier model or the default route:
`no` refuses and `unknown` is sent. A held model and the router's own choice are never gated into
`unknown`: a held model is kept only when `accepts == yes` for the required kinds (else the router
chooses afresh), and the router substitutes only models answering `yes`. Task 5.4 adds the parameter
(default empty) and uses the real `accepts` and `preset_accepts` (media 2.1 lands first in the
canonical order); media 2.3 later passes the real kinds, and `inherited_kinds` is a hook
returning the empty set until media 3.1.

**D8. Explicit selectors and a named tier.** The resolution order stays: conflict check, `tier`
rules, then `depth` (a preset, verbatim), `model` (verbatim, no `reasoning` sent, never rewritten,
never checked against the shortlist or the matrix; the one exception is the attachment gate of
`media-attachments`, which gates every final route, with `unknown` sent only for an explicit model, a pin, a tier model or the default route), then the mode's default. The router fills only
the nameless case in `dynamic` mode. A named `tier` in `dynamic` mode skips the tier classifier (no
Decisions request) but the offline rules still classify the task class (no upstream call); the router
(or a pin) then chooses the model for that tier; `selected_by` is `tier`, `classifier` null. With a
pin and a named tier the pinned model runs, `selected_by` is `tier` and the reason says pinned. A
classified tier with a pin reports `router` and `pinned`.

**D9. Modes and settings: a backward-compatible path (recommended; restructure is allowed because
2.1.0 to 2.3.0 are unpublished).** `standard` (one model, `PERPLEXITY_MODEL`) and `custom` (three
required tier models) keep their behavior; `dynamic` becomes the router. `PERPLEXITY_TIER_LIGHT|
STANDARD|COMPLEX` stay valid in `dynamic` mode as pins: that tier's calls run that model verbatim,
the effort still follows D5. `PERPLEXITY_MODEL` is ignored in `dynamic` mode with the warning custom
mode already gives (this replaces the shadow warning). `settings.DYNAMIC_PRESETS` and
`dynamic_target` go away. Not chosen: a new mode name (it would rename a mode nothing published uses
and orphan the docs) and dropping `tier` (explicit control is the escape hatch an agent needs).

**D10. Where the call is shaped.** A routed call is shaped like an explicit-model call (web search
tool, `max_steps` 3, `search` false allowed, the `anthropic/` output cap), plus `reasoning.effort`
when D5 chose a level; the request builder gains one optional argument. Presets bundle more
grounding (documented: `medium` is two searches plus two fetches); an unmeasured step budget could
make a routed answer weaker than the preset it replaced, so the evaluation measures grounding and the
budget may become a function of the tier (open question 4).

**D11. Research.** (An omitted depth, null, is resolved inside the tool body before
`build_research_request`, which refuses a null depth today and keeps doing so: the default preset
outside `dynamic` mode, the router in it; a caller-sent `routed` is refused by the same depth check.
Pins apply to routed research; research carries no attachments.)
`perplexity_research.depth` becomes `str | None` with default `None` (today it
defaults to the string `medium`, which cannot be told from an explicit `medium`). Behavior: a named
depth is a preset in every mode; omitted means `medium` outside `dynamic` mode (so existing behavior
is exact) and routed in `dynamic` mode (rules classification only, never the Decisions classifier, so
a research submit makes no extra request). Impact of the signature change: (1) the schema property
changes from a string with `"default": "medium"` to `anyOf [string, null]` with default null (measured
194 against 170 bytes with the same description); (2) `command.py` builds flags from the schema, and
`_default_of` skips a null default, so `--depth` shows no `(default: ...)` suffix and the description
carries the default instead; (3) the README, `help_text.py` and the tool description say "omitted:
medium, or the server's choice in dynamic mode"; (4) `ResearchResult.depth` is `str` and may be
`routed`. Routed submit: the background request carries `model`, `reasoning.effort` (when chosen),
the web search tool and the step budget. Whether the API accepts `background: true` with an explicit
model and `store: true` is unprobed: task 1.2 probes it first. If refused, nameless research in
`dynamic` mode runs the tier's preset (D6) and these are amended before apply, an exhaustive list:
`routing-config` "Routing mode" (research stays unchanged in every mode; the "Research is unaffected"
scenario keeps its current wording) and "Dynamic mode routes by a classifier" (drop the research
query); `routing-evidence` "The tier gives a target effort" (its research scenarios), "Research falls
back to its preset" and the research cap; `routing-decisions-classifier` "The classifier runs only
when it is needed" (drop the "for research never" clause); `agent-research` "Research tool" (depth
stays a plain optional preset), "A nameless research run is routed in dynamic mode", "A routed job is
shown as routed", "A routed research job stores its level in its own column", the routed-job
scenarios of "Recording follows the recorder contract" and the routed scenario of "The model is known
only from a finished run"; `agent-ask` "Agent requests name the preset as effort" (wording only);
the research parts of the proposal; the `research_jobs.effort` column of migration `0006`; tasks 5.3
and 5.5. Where the preset leaks: a routed submit that returns already terminal records the preset through
`tools/research.py:158` (`preset=depth` into `run_costed`), `agent.py:678-679` (the recording calls
`snapshot_model(raw, preset)`) and `research.py:183` and `:186` (`job_columns(raw, depth, ...)`); all pass
null for a routed run, a failed submit's event included (`costed_call` records the failure with the same
preset), and the `agent-research` delta MODIFIES "Submit that returns another status". The jobs tool
leaks the sentinel today: `tools/jobs.py` `JobInfo.depth` (line 58,
description "The preset: medium, high or xhigh"), `job_info` (132) and `_line` (189), and
`tools/research.py:49`; they show depth `routed` with the model and a new `JobInfo.effort`, their
descriptions say "a preset, or `routed`", and they are in the call-site sweep. "Job records" and
"Recording follows the recorder contract" are MODIFIED in the `agent-research` delta (preset null for a
routed job).

**D12. Storage: one migration, three columns; chat holds tier and model.** Migration `0006` adds
`chat_messages.tier`, `chat_messages.routed_model` and `research_jobs.effort` (all nullable), and its
downgrade runs
`ALTER TABLE ... DROP COLUMN` for each, with no Alembic batch mode. Why: batch mode rebuilds the
table (create, copy, drop, rename), and dropping `chat_messages` or `research_jobs` would cascade
through the `ON DELETE CASCADE` keys of `embedding_chunks` and silently delete every stored vector
for chats and jobs (`CLAUDE.md`, storage section). `DROP COLUMN` needs SQLite 3.35.0 (2021-03-12);
that is already the project minimum because `storage/embeddings.py` uses `... RETURNING id` (also
3.35.0), and the SQLite of this project's environment measures 3.53.1 (`uv run python -c "import sqlite3;
print(sqlite3.sqlite_version)"`); the downgrade test asserts the `embedding_chunks` rows
survive. A routed research job stores depth `routed`: `research_jobs.depth` is `NOT NULL` (migration
`0004`) and making it nullable would need the same table rebuild, so a defined sentinel is the least
invasive choice; the level sent goes in `effort`, the model in `model` at submit; the recorder passes
preset null when depth is `routed` (the observation core reads `job.depth` at `agent.py:975`).
`snapshot_model` compares `model != depth`, which a `routed` sentinel never equals, and a routed
job's model is set at submit (the `agent-research` delta). Chat: each assistant message stores the
tier its call ran at in `dynamic` mode, a named `tier` included, so a later nameless follow-up holds
at least that tier. A follow-up with no selector holds the previous turn's model as well, but NOT from
`chat_messages.model`: `tools/chat.py:297` stores `answer.model`, the API-REPORTED id, which can
differ from the matrix id (a request for `openai/gpt-6-luna` can report `openai/gpt-5.6-luna`). The
new `routed_model` column holds the REQUESTED id of a router model route (a pin included), and is null
for a preset, the fallback preset rung, an explicit `model` and every `standard` or `custom` turn. The
hold applies only when `routed_model` is non-null, is an `available` key of the matrix and answers `yes` for every
required kind (`matrix.accepts == yes`; the required kinds are the new message's attachments plus,
for a CHAINED send, the kinds inherited from the chat's earlier turns (`inherited_kinds(chat)` of
`media-inputs`; a hook returning the empty set until its media 3.1), and the new message's attachments only
for a REPLAY, which resends no earlier file); otherwise the router chooses afresh with those kinds. The effort is recomputed from the held tier; a pin of the held tier wins; a named `depth`,
`model` or `tier` resolves afresh. A row with no stored tier uses the legacy preset
match. Continuity beats re-routing mid-conversation (a switch changes style and loses cached
context); a chained turn on a different model was probed once (`perplexity/sonar` then
`openai/gpt-6-luna`, `openspec/changes/archive/2026-10-13-routing-modes-config/design.md` D8b), and
task 1.4 probes it again. Test impact, checked with `rg` on the test tree: `tests/test_chats_migration.py:214`
(`test_the_orm_models_match_the_migrated_tables`, ORM columns against the schema at 0003) and
`tests/test_jobs_migration.py:249` (the same for `ResearchJob` at 0004) fail once the ORM models gain
columns, so each is rewritten to compare against the schema through 0006 or to account for the added
columns; `tests/test_embeddings_migration.py` is NOT affected (its scratch migrations directory is
truncated at 0005, so its `"0005"` assertions stay true); the tests that compare with `head_revision()`
(`test_jobs_migration.py`, `test_usage_events_migration.py`, `test_storage_migrate.py`) follow the head
by themselves and are re-run, not edited.

**D13. Sustainability: what happens when the catalog changes.** The router reads the matrix at call
time (the in-memory snapshot refreshed by the existing task), so none of these needs a release:

| Change | Router behaviour | Guard |
|---|---|---|
| A shortlist model is `removed` | not eligible; the next contender or the fallback answers | scenario |
| A price changes | blended price recomputed; the winner among contenders may change | scenario |
| A level becomes refused | D5 picks another level, or none | scenario |
| A new model is listed | never routed (no evidence, not shortlisted) | scenario |
| The fallback model is `removed` | the preset rung (text, search on) or `invalid_request` | scenario |
| Evidence ages | `as_of` older than 90 days: one startup warning, routing unchanged | scenario |
| A shortlist id is not in the packaged baseline | the offline suite fails | `tests/test_routing_evidence.py` |
| A shortlist id is not in the live catalog | a `live`-marked test fails | `-m live` |

**D14. Output and size budget.** `routing` gains `effort`; `selected_by` gains `router` and
`fallback`. `ConfiguredModel.preset` is removed (an unpinned tier has a null id), `RoutingSection`
gains one `evidence` string (dynamic only), and `JobInfo` gains `effort`. Measured with pydantic in the
current title-free style (bytes in `tools/list`): `Routing.effort` 115 in each of the ask and chat
output schemas (230); `JobInfo.effort` 124, counted twice for safety (248); `RoutingSection.evidence`
152; `ConfiguredModel.preset` removed -117; the research `depth` schema (`anyOf` string or null, default
null) +24; reworded depth descriptions in `ResearchResult`, `JobInfo` and the tool +9, +9 and at most +40.
Sum for the default server: 230 + 248 + 152 - 117 + 24 + 58 = 595, ceiling +650 (rounded up). The new
dynamic description sentence may add at most 70 bytes per tool (ask, chat): +140 on the two dynamic
servers, so +790. Per-server TARGETS (recorded by task 6.2; the test asserts only the cap until the final ceilings of
task 6.4 are installed from the combined table that media 3.3 writes), under the unchanged
59779 cap: default 58385 (57735 + 650), dynamic 58811 (58021 + 790), dynamic with Decisions 59045 (58255
+ 790), at least 734 bytes under the cap. If a measured figure exceeds its ceiling the descriptions are
shortened first; a ceiling is raised only with the new arithmetic written here, and never past 59779.
Combined release budget: the cap 59779 never rises. These targets are the growth of this change
alone. `media-inputs` adds its own fields after it; the headroom it can use on the largest server
(dynamic with Decisions) is 734 bytes plus the trim below. Task 6.3 trims at least 450 bytes (field
descriptions of `perplexity_chat`, `perplexity_jobs` and `perplexity_embed`, measured before and
after, wording kept accurate) BEFORE any media schema growth, so the room for `media-inputs` is at
least 1184 bytes on that server; media 3.3 then measures all three servers after its chat
parameter lands, trims at least 300 bytes more, applies its STOP rule and writes the combined table,
and task 6.4 installs the final per-server ceilings from that table (never above the cap). The
dynamic sentence keeps its 70-byte cap per tool.
The longer instructions text is not part of `tools/list`.

**D15. Observability.** The `reason` (at most 120 ASCII characters, constants and counts only, never
prompt text) names the task class, the number of contenders and the rule, for example `coding; 3
within 3.0 pts; cheapest`, or `held`, `pinned`, or the fallback rung. `perplexity_models` reports one
`evidence` line: the `as_of`, the shortlist size and how many shortlist models are eligible per class
(rendered in the text; the structured field is one string).

**D16. How `resolve` gets its inputs, and the ask two-phase resolve.** `routing.resolve` stays pure:
it gains keyword arguments `evidence` (the loaded evidence), `matrix` (a `matrix.Matrix`), `tool`,
`required_input` and `provisional`; the tools read `app.evidence.snapshot()` and
`app.matrix.snapshot().matrix` and pass them, so a test passes small literals and needs no file or
network. The order inside a call in `dynamic` mode: (1) selector conflicts and tier errors, as in
every mode; (1b) the attachment parse of `media-attachments` (kinds and size; it yields the required
kinds, empty for text only); (2) a provisional `resolve(provisional=True)` that never raises a router error and names
`fallbacks.default.model`, so option validation (`build_request` inside `AskOptions` use) runs on a
model-shaped request and a bad option always wins over a router refusal; (3) the real rules-based
`resolve(required_input=kinds)` (the router may refuse: no model for the required media, no model
rung with `search` false); (3b) the attachment gate (`accepts` of the final route); (4) only then,
when the Decisions classifier applies, `classify_dynamic`, followed by a second real
`resolve` with the classification, which changes the tier and so the effort; the model choice does not depend on the tier, so it
changes the model only when a `PERPLEXITY_TIER_*` pin of the new tier replaces it, and it cannot add a
router refusal the earlier resolve did not raise (the pin check runs before the router); (4b) when the
second resolve changed the route (a pinned model for the reclassified tier), the media gate and
`preset_accepts` run again on the FINAL route, so a pinned model that refuses the kind fails with
`invalid_request` before any model request. `tools/ask.py` today resolves once
before validation and again after the Decisions call; steps (2) and (3) replace the first call, step
(4) the second. `tools/chat.py` has two resolve sites (`chat.py:245`, the send path, and `:588`, the
validation path) and follows the same order with the hold of D12. `wants_decider` loses its `search` condition
(a `search` false call is routed like any other). The refusal text at `routing.py:134` ("with
neither, the tier is picked from the prompt") says the model and effort are picked instead, with its
tests.

## Shortlist proposal (models only; scores are not proposed)

Eight ids, all present in `data/model_matrix_baseline.json` (checked 2026-10-30), spread across
price bands and providers so each task class has several candidates; the evaluation may drop or add
any of them. `openai/gpt-6.1-terra` (the `high` preset's model) is not in the baseline dated
2026-10-17 and is therefore not proposed until the live matrix lists it.

| Model id | Input / output per 1M | Why it is a candidate |
|---|---|---|
| `openai/gpt-6-luna` | 0.1 / 0.5 | cheapest; the fallback and the documented model of `fast`, `low`, `medium` |
| `anthropic/claude-haiku-5-5` | 0.1 / 0.5 | same price band, different provider |
| `perplexity/sonar` | 0.25 / 2.5 | the standard-mode default and web-native |
| `google/gemini-3.8-flash` | 0.75 / 3.75 | mid-price flash model |
| `xai/grok-4.7` | 2 / 6 | mid-price, another provider |
| `anthropic/claude-sonnet-5-5` | 2 / 10 | mid-price Anthropic |
| `openai/gpt-6.1-sol` | 2 / 10 | mid-price OpenAI; named by the owner as an `xhigh`-class fallback (rung removed, D6) |
| `anthropic/claude-opus-5-5` | 4 / 20 | the `xhigh` preset's documented model; top of the price range |

## Risks / Trade-offs

- **Figures may be wrong or stale.** Mitigation: nothing routes on an unverified score; every score
  carries source, date and basis; verification is a live task; evidence age is surfaced.
- **Benchmark mismatch.** A benchmark is a proxy and vendors report different ones, so the class
  mapping can pick a model that is good on the benchmark and weak on the prompt. Mitigation: the
  evaluation is the publishing gate; the mapping is data the owner can change.
- **Weaker grounding on a model route than on a preset** (D10). Mitigation: measured in the
  evaluation; a tier-based step budget is the lever.
- **The research model route may be refused by the API** (D11); the probe comes first.
- **Effort names are not comparable across providers** (the research probe saw no visible effect on
  a trivial prompt for several models). Mitigation: the effort is bounded by the cap and by what the
  matrix says is accepted; its value is an evaluation question.
- **Maintenance cost.** A hand-edited evidence file can drift. Mitigation: age warning, offline and
  live drift tests, the verification procedure (task 2.4) written down.
- **Migration `0006`** touches the chat and research tables. Mitigation: nullable columns, backup
  by the existing runner, a `DROP COLUMN` downgrade (D12) that cannot cascade into
  `embedding_chunks`, and a test that the vectors survive.
- **A held model on a chat follow-up** can keep a model the evidence later ranks lower. Mitigation:
  it is dropped when `removed`, an explicit selector overrides it, and the evaluation may revisit it.
- **Vendor-reported versus independent scores** can differ by many points; D3 treats them equally.
  Open question 5.

## Migration Plan

0. CANONICAL APPLY ORDER across the two changes (`media-inputs` owns the modality facts): (1) media 1.1, 1.2, 1.3, 2.1, 2.2; (2) routing-v2 groups 0-4 and 5.1-5.3; (3) routing-v2 5.4, 5.5, 6.1, 6.2, then 6.3; (4) media 1.4, 1.5, 2.3, 2.4, 3.1, 3.2, 4.1, 4.2, then 3.3; (5) routing-v2 6.4; (6) docs for both (routing-v2 9.1 makes the single CLAUDE.md tools-list figures edit). If that order is impossible, a stub `matrix.accepts` returning `unknown` (nothing substituted, nothing refused) lets this change land alone, and `media-inputs` replaces it.
1. Land specs and code behind `dynamic` mode only; `standard` (the default) and `custom` do not change.
2. Ship the evidence file with empty `scores`; dynamic mode then routes to the fallback and
   logs one warning that no verified evidence is loaded.
3. Source and verify the figures live (tasks 2.x), then run the evaluation with `routing-eval-tuning`.
4. Only a passing evaluation allows the release; until then 2.1.0 to 2.3.0 stay unpublished.
5. Rollback: remove the evidence override file and use `standard` mode; migration `0006` downgrades.

## Open Questions

1. **Shortlist ownership.** The brief says the matrix baseline doubles as the default shortlist;
   this design reads that as "the shortlist ships in the package like the baseline and is overridable
   from the data directory". Recommendation: keep it, and do not derive a shortlist from the whole
   baseline (54 models would need 54 verified scores).
2. **Fallback targets, and the dropped `xhigh` rung.** The owner's note says `fast` falls back to
   `openai/gpt-5.6-luna` and `xhigh` to `openai/gpt-6.1-sol`; `catalog.PRESETS` says `fast` is
   `openai/gpt-6-luna` and `xhigh` is `anthropic/claude-opus-5-5`. No call can reach an `xhigh`
   fallback (never automatic; an explicit `depth` `xhigh` is verbatim), so the rung is removed.
   Recommendation: keep `gpt-6-luna` at `low` as the default rung, the preset as the last, re-read
   the documentation in task 1.3; if the owner wants `xhigh` handled, add a unavailable-preset rule
   for an explicit `depth` `xhigh` in a separate change.
3. **Standard and complex in ask and chat.** They differ only by recorded tier (same model, same
   effort). Recommendation: accept it until the evaluation shows `complex` ask prompts need `high`
   (the cap exists for the 120 s timeout).
4. **Step budget per tier.** Recommendation: keep 3 until the evaluation measures grounding, then
   raise it for `complex` if answers cite fewer sources than preset `medium`.
5. **Vendor versus independent scores.** Recommendation: equal treatment now; if the evaluation shows
   vendor-only scores over-predict, add a named `VENDOR_DISCOUNT_POINTS`.
6. **Default task class.** Recommendation: `browsing`, because every routed call is web-grounded;
   the alternative is a fourth `general` class with MMLU-Pro, which needs another benchmark verified.
7. **Light tier margin.** Should a lookup accept a wider margin and so a cheaper model?
   Recommendation: no, until the evaluation shows lookups are over-served.
8. **`xhigh` for automatic research.** Recommendation: not automatic (`RESEARCH_AUTO_MAX = high`);
   the owner may raise it per the cost range stated for research.
9. **Decisions classifier choosing the task class.** Recommendation: no; the rules supply the class
   offline, and the Decisions default stays `pplx-decider-v1.1-27b` until its evaluation.

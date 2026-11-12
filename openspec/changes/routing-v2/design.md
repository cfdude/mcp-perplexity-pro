# Design

## Context

Dynamic mode today: `rules.classify(text)` (or the Decisions classifier) returns a tier, and
`routing.dynamic_route` maps the tier to preset `fast`, `PERPLEXITY_MODEL` or preset `medium`
(`settings.dynamic_target`). The matrix (`matrix.py`, `matrix_refresh.py`, baseline
`data/model_matrix_baseline.json`, 54 swept models plus any entry added later with unprobed inputs) holds, per model, `status`, per-million prices and the
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
- No savings, speed or quality claim in any document until the in-branch evaluation (D18) reports PASS
  on every pre-registered threshold; after it does, documents may quote the measured figures with the
  report as the source. No escalation or retry one tier up (the model-gone retry of D17 is one retry of
  the same call, not an escalation); no router API backend; no change to the classifier defaults; no
  media inputs.
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
light `browsing` lookup. **Owner decision 2026-11-11:** the mapping above and the margin of **3 points** (D4) are approved as
drafted. Owner edits after that: benchmark ids, class membership, the vocabularies and the margin, each
editable only until the pre-registration of D18 (task 7.2); an edit after a scored run starts a new
numbered evaluation run.

**D3. Selection algorithm (pure; `routing_select.select(...)`).** Inputs, all passed as arguments:
the task class, the tier, the tool (`ask`, `chat`, `research`), the evidence, a matrix snapshot
(`matrix.Matrix`), `required_input` (a frozenset drawn from `{"image", "document"}`, default empty = text only), `exclude` (a frozenset of ids the caller derives from the retirement holder of D17, so `select` reads no state), the margin and
`search`. Steps:
1. Eligible = shortlist models that are `available` in the matrix, are not tombstoned by a retirement
   (D17) and, when the process already holds a catalog listing in memory, are listed in it (selection
   never fetches the listing), have both prices non-null, answer
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
`fallbacks.default` (`openai/gpt-6-luna`, `low`) when `available`, not excluded or tombstoned, listed in the held listing (D17) and `accepts(...) == yes`; its `low`
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
misroute, and task 1.3 re-reads the documentation. **Owner decision 2026-11-11:** the last-resort
fallback for a task the chain cannot place is the request's own preset model (rung (c), unchanged);
`anthropic/claude-opus-5-5` stays an allowed top-of-shortlist model; no `xhigh` automation is added
(open questions 2 and 8).

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
chooses afresh), and the router substitutes only models answering `yes`. Task 5.3a (router-free, media-owned scaffolding) adds the parameter
(default empty) and 5.4 uses the real `accepts` and `preset_accepts` (media 2.1 lands first in the
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
The longer instructions text is not part of `tools/list`. D17 and D18 add no schema bytes (the retirement note is an existing string, the hint is error text, the evaluation adds no tool field).

**D15. Observability.** The `reason` (at most 120 ASCII characters, constants and counts only, never
prompt text) names the task class, the number of contenders and the rule, for example `coding; 3
within 3.0 pts; cheapest`, or `held`, `pinned`, or the fallback rung. `perplexity_models` reports one
`evidence` line: the `as_of`, the shortlist size and how many shortlist models are eligible per class
(rendered in the text; the structured field is one string).

**D16. How `resolve` gets its inputs, and the ask two-phase resolve.** `routing.resolve` stays pure:
it gains keyword arguments `evidence` (the loaded evidence), `matrix` (a `matrix.Matrix`), `tool`,
`required_input` and `provisional` (the last two and the call order below are the router-free scaffolding of task 5.3a; the router logic is 5.4); the tools read `app.evidence.snapshot()` and
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
(a `search` false call is routed like any other). The refusal text at `routing.py:138` ("with
neither, the tier is picked from the prompt") says the model and effort are picked instead, with its
tests.

**D17. A retired model forces one bounded refresh and one retry (owner requirement 2026-11-11).**
Model names are stable families (`luna`, `sonar`, `haiku`, `gemini`) while version numbers retire, so a
shortlist id can stop being served between two scheduled matrix refreshes. Trigger: a model-bearing
upstream request REJECTED before the API accepted it, whose answer satisfies
`matrix.model_not_served(status, message, model)` (owned by `media-inputs` task 2.1, the same classifier its
baseline rules and input probe use: the API's 400 `validation failed: model ... is not supported`, and a
404 or 410 only when the message names the requested id, so a job poll's 404 or a proxy 404 never matches;
this change adds no second classifier). A timeout, a 5xx or any failure after acceptance is never retried
by this rule (the request may already be billed). Steps, in order, for one call:
1. The failed call is recorded as today (`costed_call` records the failure, category from the status, no
   usage) but now carrying the failed model: `costed_call` and `agent.run_costed` gain an optional
   `model=` argument (default None) that the failure `record_usage` passes through, so the usage log
   shows WHICH model failed. `record_usage(` keeps exactly its two lines in `costed.py`, and the five
   callers of `costed_call` stay five (`tests/test_contract_checks.py`, the five-caller assertion near
   line 1197, is unaffected by a keyword). The sweep lists `costed.py`, `agent.run_costed` and its three
   routed callers (ask, chat send, research submit, which pass `model=`) and the other four
   `costed_call` callers (`search.run_search`, `decisions.run_decide`, `embeddings.run_embed`,
   `matrix_refresh.probe_request`), which keep the default. The failed id is tombstoned for 300 seconds
   (`GONE_TTL`).
2. `MatrixState.refresh_now(failed_id)` runs: single-flight (concurrent failures share one fetch), and
   rate-limited to at most one listing fetch of ANY origin per 300 seconds per process
   (`FORCED_REFRESH_MIN_INTERVAL`, a named constant, not a setting): the scheduled refresh, a
   `perplexity_models` refresh and a FAILED fetch all stamp the window, so inside it `refresh_now` returns at
   once and the snapshot is used. It reads only the API's own `/v1/models` through the existing
   `Catalog.get(refresh=True)` (no documentation is read or scraped), merges with the existing rules (a
   vanished id becomes `removed`; an empty or under-half listing changes nothing, which keeps an outage
   from emptying the matrix) and NEVER calls `probe_new` or any probe: it spends nothing and writes no
   usage event. A failed fetch is recorded and consumes the window, so an outage cannot loop.
3. Retry, only for a model the SERVER chose (the router, a named-tier router route, the fallback model rung,
   a held chat model), exactly once: the pure selector runs again with `exclude` (a frozenset the caller
   builds from the holder below, so `select` stays pure) and the live ids known; it prefers the best
   remaining shortlist model of the same family (family key: the provider plus the name tokens that are not
   version tokens, so `anthropic/claude-haiku-5-5` and `anthropic/claude-haiku-6` share
   `anthropic/claude-haiku`; version tokens match `^v?[0-9]+([.][0-9]+)*$`; the newest live version is the
   one with the greatest numeric tuple, ties to the smaller id), chosen by the normal D3 rules; with none,
   the chain fallback of D6 (research: the tier's preset). The exclusion, the held-listing filter and the
   tombstones apply to `fallbacks.default` too: a retired fallback model falls through to the preset rung.
   A live successor that is NOT on the shortlist has no evidence and is never routed: it is named in a log
   warning and in the error hint so the owner can add it. The retry request is the only extra upstream
   call; if it too says not served there is no second refresh and no second retry: the call fails with the
   hint.
4. The result's `routing.reason` begins `model_retired:<id>` (the id cut to 64 characters, the rest clipped
   so the reason stays within 120). `selected_by` keeps the failed route's value (`router`, or `tier` for a
   named-tier route) when the retry ran on a same-family model, and is `fallback` when it ran on the chain
   fallback. The usage log holds two events, the failed one (its model the retired id) and the retry.
State: one small mutable holder on `AppContext` (the `MatrixState` pattern: a frozen context holding a
reference to a mutable object), built with an injected monotonic clock, holds the tombstones (id to
expiry), the window stamp and the refused-effort marks (below). `select` never reads it; the caller turns it
into `exclude` and `live_ids`. A model that keeps answering 400 while the listing still shows it is
eligible again after 300 seconds, so it costs at most one failed call and one retry per model per 300
seconds per process. Assumption, tested and probed: a not-served 400 is UNBILLED (the body has no usage
block); task 1.5 checks it, the failed event is stored with unknown cost, and a test asserts the event
carries no usage.
Effort refusals are a different failure. A 400 on a request that carried `reasoning.effort` and that
`matrix.is_effort_refusal` recognises (its text captured by task 1.5; if the captured body is only the
generic `invalid request`, the predicate is "a 400 on a request that carried `reasoning`, that is neither
not-served nor a named modality refusal") is NOT a retirement: `model_not_served` must not match it. The
server retries once on the SAME model WITHOUT `reasoning` and marks that level refused for that model in
this process (the holder), so D5's clip then picks another accepted level or none. The one retry of a
call is shared by the two rules. The chat `continuation_hint` (advice to resend with `replay`) is not
shown for either answer, and its wording is otherwise unchanged.
Composition: an explicit `model`, a `PERPLEXITY_TIER_*` pin and a mode default model (`standard`,
`custom`) are named by the caller or the operator and are NEVER silently replaced: the refresh still runs
(free, bounded) but there is no retry; the error keeps its category by status and its text gains `Model
<id> is no longer served; nothing was substituted. Live models of the same family: <up to five ids, newest
first>` (or says none are listed), and for a pin or mode model names the variable. This hint outranks
`schema_hint`, `continuation_hint` and `media-inputs`' `attachment_hint`; media 2.3 is the ONE owner of that
precedence (it places the real `attachment_hint` below the model-gone hint), and routing 5.6 only stubs the
media hint. A held chat model is the router's own earlier choice, so it follows the router rule and the
reply stores the model that actually answered as `routed_model`. A preset is a name the API resolves, not an
id the matrix lists: no refresh, no retry. The Decisions classifier's model is outside the rule (its failure
already falls back to the rules). Research: a routed background submit follows the router rule at submit
only (one refresh, one retry, then the tier's preset, never `gpt-6-luna`); a research run that ends on the
tier's preset is an ORDINARY preset job (depth the preset's depth, `effort` null, the event's preset set),
and only a run that ran a model has depth `routed`. A chained chat turn retried on another model keeps its
`previous_response_id` (the API keeps the chain across a model switch, `media-inputs` probes S3 and S4,
task 1.4 re-probes it). Cost: nothing beyond the one retry call; no schema bytes.
Honest limit, ACCEPTED by the owner 2026-11-11: the shortlist normally holds one version per family, so the
same-family step usually finds nothing and the retry lands on the chain fallback; the value is that the call
succeeds and the successor is named.

**D18. The measuring stick: an in-branch, merge-blocking evaluation (owner requirement 2026-11-11).** Rob:
routing must deliver value, not bloat; no added user-facing delay or token overhead; it must be fast and
efficient and produce usage savings (cheaper models for lighter work); "if we can't prove those things,
we keep it in a branch and do not merge". The evaluation therefore lives in this change (spec
`routing-evaluation`; harness in `tests/routing_eval/`; report `acceptance/evaluation.md`), replaces the
old publishing-gate hand-off to `routing-eval-tuning`, and blocks the merge. Four arms, one request
shape, each under its own `project`: ROUTED; STRONGEST, the named model `anthropic/claude-opus-5-5`
(global, pre-registered, deliberately NOT derived from the evidence, which would be circular because the
evidence is the thing under test); CHEAPEST (lowest blended price among available shortlist models, ties to
the smaller id by the D3 rule); and STATUS QUO, the route a nameless call takes today (`perplexity/sonar`,
`standard` mode, explicit-model shape, no `reasoning`, as of commit d2798cd), so the evaluation answers "is
it better than what we ship now", not only "is it better than the most expensive thing". The latency and
token baselines (T2a, T3c) are the same prompt with `model` set to the model the routed call chose (a
"configured model" has no meaning in `dynamic` mode). Thresholds, proposed by the author and EDITABLE BY THE
OWNER, like the D2 table, until the pre-registration commit of task 7.2:

| Id | Threshold | Why this value |
|---|---|---|
| T0 | at least 15 main and 5 held-out prompts per class, at least half of each subset machine-checkable | the owner's 12 raised so a class has 15 paired points; held-out frozen after task 3.1 so tuning cannot see it |
| T1a | `resolve` plus `select` p95 under 5 ms in each of three evidence states (shipped empty, verified, worst-case synthetic) | a pure function over small tables; the worst case has every baseline model scored and within the margin |
| T1b | 0 added network calls on the default and rules paths | the router reads in-memory snapshots; any fetch in the call path is added delay |
| T2a | median added wall time under 50 ms (paired, same stub upstream, each evidence state) | below human notice with a 2x margin; the stub isolates the server's own overhead |
| T2b | live median latency, routed against status quo, at most 1.10 | cheaper models should not be slower than today; 10 percent allows live noise |
| T2c | cold start under 100 ms | the evidence file and matrix are read once per process, lazily |
| T3a | `tools/list` at most 59779 on the three servers | the existing cap, which never rises |
| T3b | `routing` object at most 400 bytes, a `model_retired:` reason included | `reason` is capped at 120 characters; 400 leaves 2x headroom |
| T3c | `input` byte-identical, only `reasoning.effort` differs | zero added input tokens |
| T4a | routed cost at most 0.75 times the strongest arm | the owner's "at least 25 percent lower" |
| T4b | routed cost at most 4.0 times the cheapest arm | stops the trivial win of picking a strong cheaper model: routing must stay near the floor on light work |
| T4c | routed cost at most 1.00 times the status quo | routing must not cost more than shipping nothing |
| T5a | 95 percent lower bound of paired routed minus strongest, overall, at least -0.10 | see the statistics paragraph |
| T5b | the same bound per class at least -0.15 | n is 15 per class, so the bound is wider |
| T5d | the same bound, routed minus status quo, overall, at least -0.10 | routing must not be worse than today |
| T5c | Cohen's kappa of the judge against the checks, on the checkable half, at least 0.70 | a judge that disagrees with ground truth cannot decide parity |
| T5e | strongest minus cheapest overall at least 0.15, else INVALID | a flat set cannot show parity |

Statistics: paired, one-sided non-inferiority. For each comparison the per-prompt score differences are
bootstrapped (10000 resamples, fixed seed, stratified by class) and the 5th percentile of the mean is the
95 percent lower bound; it must be at least minus the margin. The margins are chosen against the noise:
with a per-prompt standard deviation of the paired difference of about 0.25, the bound sits about 0.06
below the mean at n = 45 and about 0.11 below at n = 15, so margins of 0.10 overall and 0.15 per class let
true parity pass while a real loss of 0.10 or more fails. They are owner-editable; point estimates alone
(the first draft) would have passed a 0.05 loss that is indistinguishable from noise at this n.
Judge: `perplexity_decide` `choice` questions with arm labels removed, answers shuffled by a fixed seed, one
recorded judge model, and the `check` label and expected value never shown to it; validity is kappa, not raw
agreement (raw agreement is inflated when most answers are right); the report gives the judge's mean score
per arm and flags an arm whose judge score differs from its check score by more than 0.10.
Held-out: run 1 scores the `main` subset only; any run after a change of margin, mapping, shortlist or
evidence also scores `heldout`, and its PASS needs the held-out point differences at least the margin and the
cost ratios to hold on it. Reuse: a later run reuses the strongest, cheapest and status-quo answers by
request-body hash (those arms do not depend on the router), and the routed answers only for prompts whose
chosen model and effort are unchanged; the judge re-scores the pooled blind set each run.
Honest fallback rule: the shipped evidence has EMPTY scores, so the router always falls back and cannot beat
the baseline; the evaluation refuses to score a run unless sourced and verified scores (tasks 2.2 and 2.3)
make the router, not the fallback, choose for at least 75 percent of EACH class (not of the set as a
whole: a fully falling-back class would hide behind two good ones); otherwise INVALID. If, with verified
evidence, T4a, T4b, T4c, T5a, T5b or T5d fail, the outcome is DO NOT MERGE the routed selection.
Budget: all live work of the branch (probes, 7.1, pilot, runs, re-runs) stays under 10 USD (the owner's
standing cap is 50 USD; this is the branch's stated figure). Proposed caps: pilot 0.50, strongest 4.00,
routed 1.20, status quo 0.60, cheapest 0.30, judge 0.10 (a decider prices input tokens at 20 nano-USD),
reserve 1.20 (held-out run and re-sends of unknown-cost requests) = 7.90; other live work 1.30 (media 1.1
and 5.1, probes 1.x, 7.1, the figure-sourcing research of 2.2) = 9.20, under 10.00. The harness sets
`max_output_tokens` and stops before a request whose upper bound would exceed its cap (the larger of 1.5
times the pilot's largest cost for that arm and the cost of `max_output_tokens` plus 50000 input tokens at
the model's prices). A 6-prompt PILOT outside the labeled set runs before pre-registration, measures cost per
arm, counts toward the budget and informs the caps only (its quality results never move a threshold); if it
projects the strongest arm over its cap the owner decides before registration. A request with unknown cost
is re-sent once from the reserve; only a second unknown makes that arm INVALID. Cost is reconciled to the
nano-USD against the harness's own client-side sums of each response, not only `perplexity_usage`. Also
recorded per arm: search-call count, cached tokens and output tokens.
Code freeze, a DELIBERATE exception to "Gate 2 after docs" for this change: the report is valid only for the
`src/` it measured, so `src/` is frozen and Gate 2 over the CODE is recorded BEFORE pre-registration (media
5.1 and 6.1 to 6.5, routing 7.1 and 8.1, 8.2, 8.3, 8.5, then the offline unwind rehearsal 7.1a); the
documentation and the harness under `tests/routing_eval/` follow, and each change's final review is
docs-only (routing 9.2, media 7.2). Any `src/` commit after the report requires a new numbered run within
the remaining budget. The merge gate is mechanical: a test run in CI on the pull request parses
`acceptance/evaluation.md`, asserts `MERGE ALLOWED` and that its recorded head equals HEAD or no `src/` file
changed since it; it may be skipped only when the report is absent and the tree holds none of
`routing_select.py`, `routing_evidence.py`, `data/routing_evidence.json` and migration `0006` (the
`media-inputs`-alone tree); the CI checkout must fetch enough history for `git diff`.
Re-runs: thresholds never change; a change of margin, mapping, shortlist or evidence after a run is a new
numbered run reported beside the earlier ones, and the budget bounds how many can happen.
Isolation: all of this work happens in a separate git worktree (task 0.4). The live pm2 app runs from the
main checkout with autorestart; a tree carrying migration `0006` that restarted there would migrate the live
database to a revision the main code does not know. Evaluation runs use a temporary data directory, never
`~/.perplexity-pro`.
Dependency analysis (what `media-inputs` consumed from this change, and what unwinding takes), computed
from the two task lists:
- Migration `0006` (5.2): NOT used by `media-inputs` (it adds no column and asserts nothing about `0006`,
  its task 3.2), so dropping it returns the head to `0005`. But task 5.3's research parts (the
  `research_jobs.effort` storage, the `routed` depth, the jobs-tool `effort` field, the optional research
  `depth`) depend on that column, so 7.8 reverts ALL of 5.3 with it, `build_request`'s optional
  `reasoning` argument included (media 1.4's composition assertions for `reasoning` go with it).
- Task 5.4 is split. 5.3a is MEDIA-OWNED, router-free scaffolding that SURVIVES an unwind: the
  `required_input` and `provisional` keyword arguments of `routing.resolve` (ignored by every non-router
  path), the D16 call order in `ask.py` and both chat resolve sites, and the `inherited_kinds` hook (media owns
  `inherited_kinds` from 5.3a onward; media 3.1 replaces its body). 5.4 is router-owned logic: `evidence`,
  `matrix`, `tool`, selection, effort, `Route.effort`, the stored tier and `routed_model`. Media tasks
  1.5, 2.3 and 3.1 build on 5.3a only.
- On unwind the attachment gate checks `route.model` (or `route.preset` through `preset_accepts`) of the
  EXISTING resolve; no held-model or router-substitution rule survives.
- The 450-byte description trim (6.3) and the per-server ceilings (6.4): standalone, media's gross growth
  (at most 900 bytes) fits under the cap with headroom of 2044, 1758 and 1524 bytes on the three servers
  (59779 minus 57735, 58021 and 58255), so media's task 3.3 needs no trim and sets its own ceilings.
- The single `CLAUDE.md` tools-list edit (routing 9.1) moves to media 7.1 when routing is dropped.
- Spec text in `media-inputs` that names the router, a held model or `routing-v2` D12 (the
  `media-attachments` requirements "A held model is kept only when it can take the kinds" and the router
  scenarios of "An unknown model is let through" and of the model-selection requirement, the `agent-chat`
  requirements that store `tier` and `routed_model` and name router input, and design D13a) becomes
  conditional and is amended by task 7.8; media task 0.4 marks them.
- The terra baseline entry (2.5) is an added entry, not a count change; 7.8 removes it.
- `matrix.model_not_served`, `is_named_refusal` and `inherited_kinds` are media's and are NOT unwound;
  only the retry (5.6) goes with the router.
Unwinding is a revert PLUS manual conflict resolution, not a clean revert: the canonical apply order puts
`media-inputs` 1.4, 1.5, 2.3 and 3.1 on top of routing 5.3a, 5.4, 5.5 and 5.6 in `ask.py`, `chat.py`,
`routing.py` and the tests. The epic's `--attribute-commit` list names the routing commits; revert them in
reverse landing order, resolve the conflicts by hand, then run the FULL pytest, ruff and `openspec validate
media-inputs --strict` and RERUN media's Gate 2 (its 6.5) on the unwound tree. Because that is
expensive to discover late, an OFFLINE REHEARSAL (task 7.1a) builds the media-only tree in a throwaway
worktree after the code freeze and runs its suite before any evaluation spend. If `media-inputs` then
ships alone, its matrix and the existing dynamic mode remain unpublished under the owner's hold of
2026-10-29 (the matrix and dynamic mode exist in the unpublished 2.1.0 to 2.3.0 releases): task 7.7 records
"owner decision required before any tag; default: nothing published". A persistent data directory must
never be opened by this branch (a database at revision `0006` is refused by a build that stops at `0005`).

## Shortlist proposal (models only; scores are not proposed)

Eight ids, spread across price bands and providers so each task class has several candidates; the
evaluation may drop or add any of them. **Owner decision 2026-11-11:** `xai/grok-4.7` is replaced by
`openai/gpt-6.1-terra` (the `high` preset's model), which the LIVE `/v1/models` listing of 2026-11-11
confirms. Seven ids are in `data/model_matrix_baseline.json` (checked 2026-10-30); `openai/gpt-6.1-terra` is
NOT, so it needs a baseline entry with its live price read at apply time (task 2.5; its `inputs` are
`unprobed`, because the 2026-10-30 sweep did not cover it) before the offline drift test of task 2.4 can
pass. `xai/grok-4.7` stays out of this round. Its 2026-10-30 media refusal was stale: the probe of
2026-11-11 (`media-inputs/acceptance/grok-4-7-investigation.md`) shows it accepting image and document, and the
repo research rates it strong on coding and agentic work at 2 / 6 USD per 1M. It is a candidate for a
LATER shortlist round, and is not added now.

| Model id | Input / output per 1M | Why it is a candidate |
|---|---|---|
| `openai/gpt-6-luna` | 0.1 / 0.5 | cheapest; the fallback and the documented model of `fast`, `low`, `medium` |
| `anthropic/claude-haiku-5-5` | 0.1 / 0.5 | same price band, different provider |
| `perplexity/sonar` | 0.25 / 2.5 | the standard-mode default and web-native |
| `google/gemini-3.8-flash` | 0.75 / 3.75 | mid-price flash model |
| `anthropic/claude-sonnet-5-5` | 2 / 10 | mid-price Anthropic |
| `openai/gpt-6.1-sol` | 2 / 10 | mid-price OpenAI; named by the owner as an `xhigh`-class fallback (rung removed, D6) |
| `openai/gpt-6.1-terra` | live price at apply time (task 2.5) | OpenAI, the `high` preset's model; replaces `xai/grok-4.7` (owner, 2026-11-11) |
| `anthropic/claude-opus-5-5` | 4 / 20 | the `xhigh` preset's documented model; top of the price range |

## Risks / Trade-offs

- **Figures may be wrong or stale.** Mitigation: nothing routes on an unverified score; every score
  carries source, date and basis; verification is a live task; evidence age is surfaced.
- **Benchmark mismatch.** A benchmark is a proxy and vendors report different ones, so the class
  mapping can pick a model that is good on the benchmark and weak on the prompt. Mitigation: the
  evaluation of D18 is the merge gate; the mapping is data the owner can change.
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
- **The live pm2 app shares this checkout.** A branch tree carrying migration `0006` that restarted there would migrate the live database. Mitigation: a separate worktree (task 0.4), temporary data directories for every run, worktree cleanup at the end (9.4).
- **Media alone still publishes the matrix.** `media-inputs` rides on the matrix and the existing dynamic mode, which the owner holds unpublished. Mitigation: task 7.7 records that an owner decision is required before any tag.
- **A held model on a chat follow-up** can keep a model the evidence later ranks lower. Mitigation:
  it is dropped when `removed`, an explicit selector overrides it, and the evaluation may revisit it.
- **Vendor-reported versus independent scores** can differ by many points; D3 treats them equally.
  Open question 5.
- **The router may not beat the baseline** (the owner's stick, D18). With empty shipped scores it
  cannot; with sourced scores it may still lose on cost or quality. Mitigation: the evaluation is
  merge-blocking and pre-registered; failure leaves the branch unmerged and `media-inputs` shippable.
- **A small prompt set is noisy** (12 per class): a class mean moves 0.083 per prompt. Mitigation:
  T5b is looser than T5a, the judge is validated (T5c), and more prompts may be added before
  pre-registration.
- **Retirement handling can mask a mistake**: a retry on the fallback hides a stale shortlist.
  Mitigation: the reason says `model_retired:<id>`, a warning names the live successor, and the
  retry happens once with a rate-limited refresh, never a loop (D17).

## Migration Plan

0. CANONICAL APPLY ORDER across the two changes (`media-inputs` owns the modality facts): (1) routing-v2 1.1 to 1.5 and media 1.1, 1.2, 1.3, 2.1, 2.2; (2) routing-v2 groups 0, 2, 3 and 4, then 5.1 to 5.3a; (3) routing-v2 5.4, 5.5, 5.6, 6.1, 6.2, then 6.3; (4) media 1.4, 1.5, 2.3, 2.4, 3.1, 3.2, 4.1, 4.2, then 3.3; (5) routing-v2 6.4 and 7.1, and media 5.1; (6) the CODE FREEZE: routing-v2 8.1, 8.2, 8.3 and 8.5 and media 6.1 to 6.5 (Gate 2 over code), then routing-v2 7.1a, the offline unwind rehearsal; (7) routing-v2 7.1b and 7.2 to 7.7, the in-branch evaluation (7.8 only if it fails), any `src/` commit after 7.6 requiring a new numbered run; (8) docs for both (routing-v2 9.1 makes the single CLAUDE.md tools-list figures edit, then routing-v2 8.4 and 8.6; media 7.1), then the docs-only reviews routing-v2 9.2 and media 7.2; (9) routing-v2 9.3, the merge gate, then 9.4, the worktree cleanup, and the archives (routing-v2 9.5, media 7.3). If that order is impossible, a stub `matrix.accepts` returning `unknown` (nothing substituted, nothing refused) lets this change land alone, and `media-inputs` replaces it.
1. Land specs and code behind `dynamic` mode only; `standard` (the default) and `custom` do not change.
2. Ship the evidence file with empty `scores`; dynamic mode then routes to the fallback and
   logs one warning that no verified evidence is loaded.
3. Source and verify the figures live (tasks 2.x), freeze the code (Gate 2 over code), rehearse the unwind
   offline, then pilot, pre-register and run the in-branch evaluation (D18, tasks 7.1a to 7.6).
4. Only a report with every threshold PASS allows the merge and the release; until then 2.1.0 to 2.3.0
   stay unpublished and the branch stays unmerged. On FAIL or INVALID, task 7.8 unwinds the routed
   selection and `media-inputs` can merge alone (nothing is tagged without an owner decision, D18).
5. Rollback: remove the evidence override file and use `standard` mode; migration `0006` downgrades.

## Open Questions

1. **Shortlist ownership.** The brief says the matrix baseline doubles as the default shortlist;
   this design reads that as "the shortlist ships in the package like the baseline and is overridable
   from the data directory". Recommendation: keep it, and do not derive a shortlist from the whole
   baseline (54 models would need 54 verified scores).
2. **RESOLVED 2026-11-11 (owner): fallback targets and the dropped `xhigh` rung.** The owner's note says `fast` falls back to
   `openai/gpt-5.6-luna` and `xhigh` to `openai/gpt-6.1-sol`; `catalog.PRESETS` says `fast` is
   `openai/gpt-6-luna` and `xhigh` is `anthropic/claude-opus-5-5`. No call can reach an `xhigh`
   fallback (never automatic; an explicit `depth` `xhigh` is verbatim), so the rung is removed.
   Recommendation: keep `gpt-6-luna` at `low` as the default rung, the preset as the last, re-read
   the documentation in task 1.3; if the owner wants `xhigh` handled, add a unavailable-preset rule
   for an explicit `depth` `xhigh` in a separate change. Answer: keep it; the last resort for a task
   the chain cannot place is the request's own preset model (rung (c)); `anthropic/claude-opus-5-5`
   is an allowed top-of-shortlist model; no `xhigh` automation.
3. **RESOLVED 2026-11-11 (owner, with the `xhigh` decision): standard and complex in ask and chat.** They differ only by recorded tier (same model, same
   effort). Recommendation: accept it until the evaluation shows `complex` ask prompts need `high`
   (the cap exists for the 120 s timeout). Answer: accepted as drafted; no `xhigh` or `high` is added
   for ask and chat, and the evaluation of D18 reports quality per class, so a `complex` shortfall
   would show there.
4. **Step budget per tier.** Recommendation: keep 3 until the evaluation measures grounding, then
   raise it for `complex` if answers cite fewer sources than preset `medium`.
5. **Vendor versus independent scores.** Recommendation: equal treatment now; if the evaluation shows
   vendor-only scores over-predict, add a named `VENDOR_DISCOUNT_POINTS`.
6. **Default task class.** Recommendation: `browsing`, because every routed call is web-grounded;
   the alternative is a fourth `general` class with MMLU-Pro, which needs another benchmark verified.
7. **Light tier margin.** Should a lookup accept a wider margin and so a cheaper model?
   Recommendation: no, until the evaluation shows lookups are over-served.
8. **RESOLVED 2026-11-11 (owner): `xhigh` for automatic research.** Recommendation: not automatic (`RESEARCH_AUTO_MAX = high`);
   the owner may raise it per the cost range stated for research. Answer: not automatic; do not add
   `xhigh` automation.
9. **Decisions classifier choosing the task class.** Recommendation: no; the rules supply the class
   offline, and the Decisions default stays `pplx-decider-v1.1-27b` until its evaluation.

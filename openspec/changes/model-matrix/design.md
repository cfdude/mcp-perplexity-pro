# Design

## Context

`catalog.py` fetches `GET /v1/models` into a one-hour in-memory cache (`Catalog.get`, stale-on-failure)
and carries a dated `PRESETS` table; nothing persists model facts. The live list is only
`{id, owned_by, pricing}` per model (no capabilities); Perplexity's docs page lists 40 of the 54
live models and disagrees with the API in places (`acceptance/README.md`). Accepted `reasoning.effort`
levels can only be learned by sending requests, and 9 of 54 models differ from the common case.
See proposal.md for the motivation.

## Goals / Non-Goals

**Goals:**
- Persist model, price and effort facts, learned from the API and refreshed by the server itself.
- Never empty, never blocking, never fatal; safe when two servers share the data directory.
- Visible: `perplexity_models` shows the facts; every probe request is a recorded usage event.

**Non-Goals:**
- No routing and no use of the matrix to choose a model (`routing-v2`); no benchmark data, strengths
  or curated shortlist; no input-modality probing (`media-inputs`); no manual probe command.
- No database table or migration: a JSON file the server can lose and rebuild is the right weight.

## Decisions

**D1. Two modules.** `matrix.py` is pure and synchronous: the `Matrix` model, `load(path)` (file,
else baseline), `merge(matrix, live_models, now)`, `merge_probe(...)`, `write(path, matrix)` (temp file,
`os.replace`, mode 0600) and the lock helper; no network, no engine. `matrix_refresh.py` owns the
task: fetch through the existing `Catalog`, merge, write, probe, sleep. Alternative: put it all in
`catalog.py`; rejected because the catalog is a cache and this is state with a file, a lock and a
probe, and the pure half stays testable without an event loop.

**D2. The baseline is data in the wheel.** `src/mcp_perplexity_pro/data/model_matrix_baseline.json`,
read with `importlib.resources`, holding all 54 models and their probed efforts as of 2026-10-17,
built from `acceptance/effort-probe-2026-10-17.json` and a live-list fixture by a test-supported
rebuild (task 1.1). A model newer than the baseline is the only thing a fresh install ever probes.
Alternative: a curated eight-model baseline; rejected because the router's candidate shortlist is a
routing decision (`routing-v2`), while the facts about all 54 are already measured and free to ship.

**D3. Load order and a corrupt file.** `load` reads the data-directory file; missing, empty,
unreadable or JSON that is not a matrix gives the baseline (an unreadable or empty file is renamed
`model_matrix.json.corrupt-<UTC stamp>` before the first write, never deleted); a `version` greater than
1 gives the baseline in memory and the file is never written (a newer server owns it). Alternative:
raise at startup; rejected because the matrix is an aid, and the server must start without it.

**D4. The task lives in the lifespan.** `build_server`'s lifespan starts `asyncio.create_task`
after the app context is exposed and cancels and awaits it on exit (inside the server's 10 s
shutdown bound); the task catches every `Exception` except `CancelledError`, logs one redacted
warning and sleeps to the next interval. The in-memory matrix is held on a small mutable holder in
`AppContext` (`app.matrix`), replaced by assignment, so tools read a consistent snapshot and there
is no module-level state. `PERPLEXITY_MATRIX_REFRESH` 0 runs once.

**D5. Merge and write under the lock.** The write sequence is: take `model_matrix.lock`
(`fcntl.flock`, as `migrate.lock` does, 10 s bounded wait), re-read the file, merge the live list
and the probe results into THAT, write the temp file, `os.replace`, release. Re-reading inside the
lock is what stops two servers losing each other's rows and probing the same model twice. The merge
rules are the spec's; an empty list changes nothing (a failed fetch must never mark every model
removed). The blocking file work runs in `asyncio.to_thread`.

**D6. The probe.** For a model that is `available` and `unprobed` (re-checked inside the lock), six
requests, one per level, sequential, through `PerplexityClient.probe_effort(model, level)`: `POST
/v1/agent` with `{"model", "input": "Reply with the single word OK.", "store": false,
"max_output_tokens": 300, "reasoning": {"effort": level}}`, one attempt (`attempts=1`, the knob added
for the Decisions classifier), the 400 captured as an answer rather than raised. A 200 is accepted,
a 400 refused with its status, anything else leaves the whole model unprobed. Alternative: ask
Perplexity (an LLM) which levels each model takes; rejected: it would be a summary of docs that have
no such table and are wrong about Kimi K3. The ten-model cap per refresh bounds one start's spend
(60 requests, about $0.04 at the measured average).

**D7. Recording without a project.** Each probe request goes through `costed.costed_call` (the one
sequence), with tool `model_matrix`. `costed_call` always names a project today (`None` becomes
`default`, and the project row is created); it gains a keyword `unscoped` (default false) that
skips name validation and project resolution and records with no project, so the probe neither
creates a project nor adds events to `default`. Its callers list grows from four to five
(`CLAUDE.md` is updated), still with exactly two `record_usage(` lines. The interpreter reads the
status and usage with the existing Agent helpers.

**D8. What `perplexity_models` shows.** `CatalogModel` gains an optional `efforts` (`accepted`,
`refused`, `source`, `probed_at`), joined from the in-memory matrix by id, and the result gains a
`matrix` object (`source` `file` or `baseline`, `fetched_at`, `unprobed` count). A model the matrix
lacks has no efforts. `tests/test_tools_list_budget.py` stays the gate; the fields are optional and
short.

## Risks / Trade-offs

- [The probe spends money at startup] → only for models newer than the baseline, at most ten per
  refresh, recorded as events, off with one variable; a fresh install of this release probes none.
- [Two servers write the same file] → lock, re-read inside the lock, atomic replace; a lock timeout
  skips the write (the next refresh retries).
- [A probe is a trivial prompt, so "accepted" is not "effective"] → the matrix says accepted and
  refused only; effect is `routing-v2`'s evaluation, and the docs say so.
- [The API's error for a refused level is only `invalid request`, so a transient 400 could be
  misread as a refusal] → a refusal is a 400 on that exact level while the other levels answered;
  if all six levels answer 400, the model is recorded as refusing every effort (as three models
  do) rather than as broken, and the observation is in the file for a person to read.
- [Prices in the file go stale between refreshes] → the interval is a setting; the matrix says when
  it was fetched.
- [The baseline ages] → a refresh adds newer models as `unprobed` and probes them, so age only
  costs a few probe requests, never correctness.

## Migration Plan

No data migration. The file is created on first refresh; deleting it returns the server to the
baseline. Rollback is `PERPLEXITY_MATRIX_REFRESH=0` and `PERPLEXITY_MATRIX_PROBE=off`, or deleting
the file.

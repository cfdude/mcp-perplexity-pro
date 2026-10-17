# Design

## Context

`catalog.py` fetches `GET /v1/models` into a one-hour in-memory cache (`Catalog.get`, stale-on-failure)
and carries a dated `PRESETS` table; nothing persists model facts. The live list is only
`{id, owned_by, pricing}` per model (no capabilities); Perplexity's docs page lists 40 of the 54
live models and disagrees with the API in places (`acceptance/README.md`). Accepted `reasoning.effort`
levels can only be learned by sending requests, and 9 of 54 models differ from the common case.
See proposal.md for the motivation. Vocabulary: a *level* is one effort value (`minimal`, `low`,
`medium`, `high`, `xhigh`, `max`); a model's *efforts* are the facts about it (accepted levels,
refused levels, how they were learned); *unprobed* means no complete answer set yet.

## Goals / Non-Goals

**Goals:**
- Persist model, price and effort facts, learned from the API and refreshed by the server itself.
- Never empty, never blocking, never fatal; safe when several servers share the data directory.
- Visible: `perplexity_models` shows the facts; every probe request is a recorded usage event.

**Non-Goals:**
- No routing and no use of the matrix to choose a model (`routing-v2`); no benchmark data, strengths
  or curated shortlist; no input-modality probing (`media-inputs`); no manual probe command.
- No database table or migration: a JSON file the server can lose and rebuild is the right weight.

## Decisions

**D1. Two modules.** `matrix.py` is pure and synchronous: the `Matrix` model, `load(path)` (file,
else baseline), `merge(matrix, live_models, baseline, now)`, `merge_probe(...)`, `write(path, matrix)`
(a `mkstemp` file in the data directory, `os.replace`, mode 0600, stale `*.tmp` of a killed writer
removed under the lock) and the lock helper; no network, no engine. `matrix_refresh.py` owns the
task, the probe and the loop. Alternative: put it all in `catalog.py`; rejected because the catalog
is a cache and this is state with a file, a lock and a probe.

**D2. The baseline is data in the wheel.** `src/mcp_perplexity_pro/data/model_matrix_baseline.json`,
read with `importlib.resources`, holding all 54 models and their probed efforts as of 2026-10-17.
It is built once from `acceptance/effort-probe-2026-10-17.json` and a live-list fixture
`tests/fixtures/models_2026-10-17.json`; the tests assert the baseline against that fixture and a
named set of the nine differing models, not against the acceptance path (which moves at archive).
Hatch's `packages` already ships non-Python files under the package, so the file needs no allowlist
entry; `tests/test_distributions.py` (build marker) asserts it is in the wheel.
Alternative: a curated eight-model baseline; rejected: the shortlist is a routing decision
(`routing-v2`), and facts about all 54 are measured and free to ship.

**D3. Load order and a corrupt file.** `load` reads the data-directory file; missing, empty,
unreadable or not a matrix gives the baseline (an unreadable or empty file is renamed
`model_matrix.json.corrupt-<UTC stamp>` before the first write, never deleted); a `version` above 1
gives the baseline in memory and the file is never written (a newer server owns it). Alternative:
raise at startup; rejected because the matrix is an aid and the server must start without it.

**D4. Where the task runs, and who stops it.** `build_server(..., matrix_refresh: bool = False)`;
only the serving path sets it: `bootstrap(serving=True)` passes it, `bootstrap(serving=False)`
(the CLI's one-shot commands), `schema_source()` and every test world leave it false, so none of
them touches the network or the file (a test proves the CLI starts no task). The task is created in
the lifespan after the context is exposed, held on a small mutable `MatrixState` in `AppContext`
(`state.matrix` for the snapshot tools read, `state.task` for the task; replaced by assignment, no
module-level state). The matrix is loaded lazily, on the first read by `perplexity_models` or the
task (`state.snapshot()`), never at `build_server`, so `schema_source()` and `help` touch no data
directory and a one-shot `perplexity-pro models` reads the file (origin `file`) without writing. Because stdio's teardown does not run the lifespan on a signal, `close_resources`
cancels and awaits `state.task` BEFORE `http.aclose()` (it is reached from the HTTP `finally`, the
stdio signal path via `_drain_and_close`, and the EOF `finally`, so one cancel covers every path; it
tolerates no task, as in the CLI); the lifespan does the same on the HTTP path, idempotently. The
loop takes an injectable `sleep`, so a test drives the interval without waiting. Test servers that
run the real serving path (`tests/fixture_server.py` calls `bootstrap()` with `serving=True`) will
start the task against their loopback upstream and log its one warning; the shutdown-order tests
must still hold. The task catches every `Exception`
except `CancelledError`, logs one redacted warning and sleeps to the next interval; interval 0 runs
once. Start logs one INFO line (settings, matrix origin).

**D5. Fetch, merge, write.** Each refresh calls `Catalog.get(refresh=True)` and treats a stale
listing (`Listing.stale`, the catalog's stale-on-failure return) as a failed fetch, so a 5xx never
merges old data and the warning fires. The write sequence is: take `model_matrix.lock` (a new
`fcntl.flock` helper in the pattern of `migrate.lock`: the lock is polled with `LOCK_NB` and
`asyncio.sleep` for at most 5 s, in the event loop and without a thread, so a cancelled wait never
takes or holds the lock), then ONE `asyncio.to_thread` call that re-reads the file, merges the live
list into THAT (the baseline supplies efforts for ids it knows), writes and releases in its
`finally`. The lock is never held across a
network request. Merge guards: an empty list, or a list with fewer than half of the stored
`available` ids, changes nothing and warns (a truncated reply must not mark the matrix removed).

**D6. The probe.** Selecting: under the lock, take up to ten `available` models with efforts
`unprobed` whose `probing_until` is null or past. Per model, in order: under the lock write
`probing_until` (now + 10 min) for that model alone, release, probe OUTSIDE the lock, then under the
lock write the answers and clear the lease in a `finally`, so a cancel, a cap or a 429 leaves no
lease behind. The control request (no effort) and then one request per level go sequentially
through `PerplexityClient.probe_effort(model, level)`: `POST /v1/agent` with `{"model", "input":
"Reply with the single word OK.", "store": false, "max_output_tokens": 300, "reasoning": {"effort":
level}}` (none for the control), `attempts=1` (the knob added for the Decisions classifier) and a 30 s
timeout, each through `costed_call` (D7), which records a response or an error (400, 429, 5xx,
timeout) with its category and re-raises; the probe catches outside it. Interpretation: a completed
200 (`agent_response_status` `ok`) is accepted; a `PerplexityError` with `status` 400 is refused, but
only when the control completed; 429 ends the round; a 5xx, a timeout, or a 200 whose run is not
`completed` leaves that level unanswered (a body that is still `queued` or `in_progress` has no
terminal state to record and counts as unanswered; a synchronous run should not return one).
Answers go to `efforts.answers` after each model, even for a model cut short, and the write is
wrapped in `asyncio.shield` and bounded by the 5 s lock wait, so a SIGTERM or stdin EOF cannot lose
paid answers (the file write is not a database unit of work, so `agent.shielded_write` does not
apply). Only when the control and all six levels have answers does the model become `source:
probe` with `probed_at` and `accepted` and `refused` filled; all six refused with a completed control
is recorded as refusing every level (three models do). Bounds: ten models, and the reported cost so
far is checked before each model against $0.25 (so the overshoot is at most one model); a floor of
300 s for any non-zero refresh interval. On the 2026-10-17 evidence the dearest model cost $0.036 for
seven requests and the ten dearest total $0.123, so the cap is a safety net that today's list cannot
reach (its test uses priced fixtures). The probe is a deliberate exception to the client spec's
retry-after-429 rule, as the Decisions classifier is: a retry sleep would stall a background round.
Alternative: ask Perplexity (an LLM) which levels each model takes; rejected: the docs have no
such table and are wrong about Kimi K3.

**D7. Recording without a project.** `costed.costed_call` always names a project today (`None`
becomes `default` and the project row is created). It gains a keyword `unscoped` (default false, which implies no project resolution whatever
`resolve_project` says):
no name validation, no project resolution, `record_usage(project=None)` (already supported and
stored as a null project name and id), and `Costed.project` becomes `str | None` (the existing callers always pass a name, and a test
asserts their results still carry it). The usage tool is
`model_matrix`; `perplexity_usage` reports these events under no project (README and help say so).
The caller list grows to five (`matrix_refresh.py`), so `tests/test_contract_checks.py` (an exact
Counter of four callers, and a ban on `costed_call` in `tools/*.py`) is updated in the same
commit as the caller; `record_usage(` keeps its two functions.

**D8. What `perplexity_models` shows.** The output models in `tools/models.py` (not `catalog.py`,
which stays pure) gain, per model, optional `efforts` (`accepted` and `refused` as short lists of
levels, and `source`) joined by id from `state.matrix`, and a `matrix` object (`origin` `file` or
`baseline`, `fetched_at`, `unprobed` count of available matrix rows). The tool reads the stored
matrix; its `refresh` argument still refreshes only the catalog list. `removed` rows are not listed,
not probed and not counted: they are history for `routing-v2` to ignore. `tests/test_tools_list_budget.py`
stays the gate (output-schema fields only); the extra result size for 54 short lists is measured in
acceptance.

**Example file**
```json
{"version": 1, "fetched_at": "2026-10-17T20:11:03Z", "models": {
  "openai/gpt-5-nano": {"provider": "openai", "status": "available",
    "pricing": {"input": 0.05, "output": 0.4, "cache_read": 0.005, "cache_write": null},
    "first_seen": "2026-10-17T20:11:03Z", "last_seen": "2026-10-17T20:11:03Z",
    "probing_until": null,
    "efforts": {"accepted": ["minimal", "low", "medium", "high"], "refused": {"xhigh": 400, "max": 400},
                "answers": {"control": 200, "minimal": 200, "low": 200, "medium": 200, "high": 200,
                            "xhigh": 400, "max": 400},
                "probed_at": "2026-10-17T19:40:00Z", "source": "probe"}}}}
```

## Risks / Trade-offs

- [The probe spends money at startup] → only for models neither the file nor the baseline knows,
  at most ten models and $0.25 per refresh, every request an event, one variable turns it off; a
  fresh install of this release probes none.
- [A bad probe could be stored forever] → a control request must complete before any 400 counts
  as a refusal; only whole answer sets mark a model `probe`; the evidence file is the check.
- [Several servers share the file] → lock, re-read inside the lock, atomic replace, a lease per
  probed model, the 300 s interval floor; a duplicate probe is bounded and recorded, not prevented
  in every race (two servers starting in the same second can both see an unleased model only if
  the first lease write is skipped by a lock timeout).
- [A probe is a trivial prompt, so accepted is not effective] → the matrix says accepted and
  refused only; effect is `routing-v2`'s evaluation, and the docs say so.
- [The matrix is stale between refreshes] → the interval is a setting and `fetched_at` is shown.
- [The baseline ages] → a refresh adds newer models and probes them (a few cents), so age costs
  requests, never correctness.
- [A read-only data directory] → migrations already refuse it at startup; a read-only matrix file
  only skips writes with one warning.

## Migration Plan

No data migration. The file is created on first refresh; deleting it returns the server to the
baseline. Rollback is `PERPLEXITY_MATRIX_REFRESH=0` and `PERPLEXITY_MATRIX_PROBE=off`, or deleting
the file.

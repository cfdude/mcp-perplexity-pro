# Call-site sweep (task 7.1)

Derived with `rg` on 2026-10-17 at `e6a00cd`.

## Who writes `model_matrix.json`
- Only `matrix.py` (`write`, reached only through `update`, which holds the lock, re-reads and
  uses `os.replace`). `matrix_refresh.py` calls `update` from `refresh_once`, `_take_lease` and
  `_finish`; nothing else opens the file for writing. Holds.

## `costed_call(` callers (five) and `record_usage(` lines (three, in two functions)
- Callers: `agent.py`, `search.py`, `decisions.py`, `embeddings.py` and now
  `matrix_refresh.probe_request`; `tests/test_contract_checks.py` names all five and still bans
  `costed_call` inside `tools/`. `record_usage(` is `costed.py` twice and the observation core in
  `agent.py`: no third function. Holds.

## Where the task starts and stops
- Starts only when `build_server(..., matrix_refresh=True)`; `__main__.bootstrap(serving=True)` is
  the only caller that passes it. `command.py:85` (`schema_source`) and `command.py:468`
  (`bootstrap(serving=False)`, the one-shot path) do not; `command.py:532` (`serve`) and
  `__main__.main` do (default `serving=True`). Holds.
- Stops: `close_resources` is called from the HTTP finally, `_drain_and_close` (the stdio signal
  path), the stdio EOF finally and `command.py:480` (one-shot, no task: tolerated); the lifespan
  also stops it on the HTTP path, idempotently. Each cancels before `http.aclose()`. Holds.

## Readers of the matrix
- Tools read it only through `app.matrix.snapshot()` (`tools/models.py`); the task adopts what it
  wrote with `adopt()`. No tool writes. Holds.

## `Catalog.get(` callers
- `tools/models.py` (the user's call, may use the cache) and `matrix_refresh.refresh_once`
  (`refresh=True`, a stale listing is a failure). Holds.

## Inverses
- A `removed` model that reappears becomes `available` (merge test); a corrupt file is renamed
  aside and the baseline used, and deleting the file returns to the baseline (load tests);
  probing off then on (acceptance d and c); an expired lease is ignored and a taken lease is
  cleared in a `finally` (probe tests).
- Not shipped, with reasons: no manual probe or refresh command (the spec lists it as a non-goal;
  deleting the file or restarting refreshes); no API to remove a model row (a vanished model is
  marked `removed`, never deleted, so history is kept).

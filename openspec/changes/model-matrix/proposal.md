# Proposal

## Why

The router work (`routing-v2`) needs facts the server does not keep: which models exist, what they
cost, and which `reasoning.effort` levels each accepts. Today the model list lives only in a
one-hour in-memory cache (`catalog.py`), and nothing records accepted efforts. Probing all 54 live
models on 2026-10-17 showed the facts differ: 45 accept every level, 9 do not (the `gpt-5` family
and `kimi-k3` refuse `xhigh` and `max`, `gemini-3.1-pro-preview` refuses `minimal`, three models
refuse every level), and Perplexity's docs list 40 of the 54 and disagree with the API on Kimi K3.
The matrix has to be learned from the API, kept on disk, and refreshed without anyone hardcoding
it.

## What Changes

- A versioned JSON file `model_matrix.json` in the data directory: per model its provider, prices,
  availability (`available` or `removed`, with first and last seen) and its effort facts
  (accepted levels, refused levels with the HTTP status, when probed, and where the facts came from).
- A packaged baseline (all 54 models with the probed efforts as of 2026-10-17) so the matrix is never
  empty, including offline or after a corrupt file.
- A refresh task started with the server, never blocking or failing startup: it fetches
  `GET /v1/models`, merges (new models added, prices updated, vanished models marked `removed`)
  and writes the file atomically under a lock, at start and then every
  `PERPLEXITY_MATRIX_REFRESH` seconds (default 86400, 0 = at start only).
- A bounded probe of NEW models only (models neither the file nor the baseline knows): a control
  request plus one tiny request per effort level, at most ten models and $0.25 per refresh, each
  request recorded as a usage event, partial answers kept, switched off with
  `PERPLEXITY_MATRIX_PROBE=off`. A fresh install probes nothing because the baseline already knows
  every model it was built with.
- The task runs only in a serving process (`mcp-perplexity-pro`, `perplexity-pro serve`); one-shot CLI
  commands, the schema builder and the test servers start none, and shutdown cancels it on both
  transports.
- `perplexity_models` reports each model's efforts and the matrix's origin.
- No routing change: nothing reads the matrix to choose a model yet (that is `routing-v2`).

## Capabilities

### New Capabilities
- `model-matrix`: the file, its baseline, its refresh and merge rules, the probe, and their bounds.

### Modified Capabilities
- `model-catalog`: `perplexity_models` reports efforts and the matrix origin.
- `server-runtime`: the two settings, the background task and its shutdown.
- `usage-recording`: probe requests are recorded under the tool name `model_matrix` with no project.

## Impact

- Code: new `src/mcp_perplexity_pro/matrix.py` (pure file, merge and baseline logic) and
  `matrix_refresh.py` (the task and the probe); `src/mcp_perplexity_pro/data/model_matrix_baseline.json`
  (packaged); `client.py` (a probe request that is one attempt with its own timeout); `costed.py` (`unscoped`,
  a fifth `costed_call` caller); `settings.py`, `server.py` and `__main__.py` (the task, its flag and
  its shutdown), `tools/models.py`, `help_text.py`; README, CHANGELOG, CLAUDE.md.
- No migration (a JSON file, not a table), no new dependency, no new tool; the `tools/list` size must
  stay under 59779 bytes (new optional fields in the `perplexity_models` output).
- Cost: a refresh is free; probing a new model is seven requests, $0.0036 on average and at most
  about $0.036 in the 2026-10-17 evidence (measured $0.197 for all 54 models and six levels); a
  refresh stops at $0.25.

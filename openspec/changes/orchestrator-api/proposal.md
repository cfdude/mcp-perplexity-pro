# Proposal

## Why

Perplexity's Orchestrator API went generally available on 2026-11-19: one key, 42 priced models behind OpenAI-format `/orchestrator/v1/chat/completions`, and a `perplexity/auto` router that picks a model per request. Its responses carry no cost, no search and no citations, so a call can only be costed from tokens. This server records every costed call, but only for four API families, and a call to the fifth would be refused by the recorder (unknown family) and could not be priced. `routing-v2` stalled the same day on missing benchmark evidence, and the auto-router is the cheapest comparison arm for its measuring stick, but that arm needs recorded, correctly priced calls first.

## What Changes

- A fifth API family `orchestrator` in the usage recorder: a usage parser for the Chat Completions `usage` object (`prompt_tokens`, `completion_tokens`, `total_tokens`, `prompt_tokens_details.cached_tokens` and `.cache_write_tokens`, `completion_tokens_details.reasoning_tokens`), registered in the parser table.
- Per-token Orchestrator prices as dated integer nano-USD constants in `pricing.py`, with each model's base rates (input, output, cache read, cache write), its long-context rates where the documentation lists them, and its minimum usage tier, pinned to a recorded copy of the documentation page and to the recorded `GET /orchestrator/v1/models` response.
- A computed cost from tokens, priced at the SERVED model (the response `model`), never at the requested `perplexity/auto`; unknown model, unknown rate or an unpriceable long-context call is an unknown cost (source `none`), never a default.
- A tier-aware model listing: a client call for `GET /orchestrator/v1/models` and a pure report that says which documented models the account can call, which it cannot, and the usage tier range that follows.
- A client call for `POST /orchestrator/v1/chat/completions` with local validation of the request (including the `routing` object) and a digest that returns the served model, the text, the usage, and the four `x-perplexity-autoroute-*` headers, plus a costed helper that records the call through `costed_call` under a caller-supplied tool name.
- A 402 (model above the usage tier) maps to the existing category `forbidden` for this API only; the vocabulary stays at eleven categories.
- Recorded fixtures of the live responses (captured 2026-11-19, tier 1 account, under $0.01 spent).
- **Not changed:** no MCP tool is added or altered (see Non-goals in `design.md`); `perplexity_models`, the model matrix and the routing modes are untouched.

## Capabilities

### New Capabilities
- `orchestrator-client`: how the server calls the Orchestrator Chat Completions endpoint: request validation, the `routing` object, response digest, autoroute headers, error mapping (402), retry rules for a billed POST, diagnostics, and the rule that no MCP tool exposes it.
- `orchestrator-pricing-tiers`: the Orchestrator model catalog as the server uses it: the dated per-token price table, the computed cost from tokens (long-context, cache read, cache write, reasoning), the minimum usage tier per model, and the tier-aware listing report.

### Modified Capabilities
- `usage-recording`: the API family set grows from four to five (`orchestrator`), and an Orchestrator usage parser and its recorded-cost rules are added.

## Impact

- Code (at apply time, not now): `src/mcp_perplexity_pro/usage.py` (`API_FAMILIES`, `_PARSERS`, a parser, `computed_usage` takes a price-table date), `pricing.py` (price and tier table, cost helper), `client.py` (two calls, a response-headers hook, a per-call status-to-category override), new `orchestrator.py` (request, digest, usage, tier report, costed helper), `costed.py` docstring (a sixth caller).
- Tests and fixtures: ten new recorded fixtures under `tests/fixtures/orchestrator_*`, a recorded copy of the documentation page excerpt, new offline tests, one live-marked test.
- Docs: `README.md`, `CLAUDE.md` (module table, caller counts, family list), `CHANGELOG.md`.
- No database migration: `usage_events.api` is free text; `usage_json` keeps the raw usage object.
- No new dependency, no new tool, no change to the `tools/list` size.

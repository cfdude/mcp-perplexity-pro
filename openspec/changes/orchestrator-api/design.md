## Context

See `proposal.md` for motivation. Facts below were verified on 2026-11-19 against the vendor pages (`docs.perplexity.ai/docs/orchestrator/{quickstart,models,routing-and-reliability,reasoning-and-caching,faq}.md`, the gateway OpenAPI) and live calls on a tier 1 account (about $0.0006 spent in total; recorded as `tests/fixtures/orchestrator_*`).

**Live-probe findings**
- `GET /orchestrator/v1/models` returns 42 entries with fields `id`, `object`, `created` (always 0), `owned_by`, `pricing{input, output, cache_read, unit, cache_write?}`; `unit` is always `usd_per_1m_tokens`. It is tier-filtered: the five tier 2 models documented on the models page (`anthropic/claude-opus-5`, `claude-opus-5-5`, `claude-fable-5`, `-5-1`, `-5-2`) are absent, so this account is tier 1. `perplexity/auto` is absent.
- The listing's `pricing` is the BASE rate only. It has no long-context rates, no tier field, no context window and no `service_tier` multipliers. Long-context rates and minimum tiers exist only on the documentation page.
- `cache_write` is present for 21 models (the 10 listed Anthropic models, 10 OpenAI models of the 6.x and 5.6 families, and `xai/grok-4.7`). For `xai/grok-4.7` it is 2.0 (1.0 times input), which the documentation page does not mention.
- Chat Completions `usage` has exactly: `prompt_tokens`, `completion_tokens`, `total_tokens`, `prompt_tokens_details{audio_tokens, cache_write_tokens, cached_tokens}`, `completion_tokens_details{accepted_prediction_tokens, audio_tokens, reasoning_tokens, rejected_prediction_tokens}`. Same shape for OpenAI, Anthropic and Google models. No cost field anywhere. `prompt_tokens` includes the cache buckets (2869 total, 2866 written on the first call, 2866 read on the repeat); `completion_tokens` includes reasoning.
- Caching on OpenAI 6.x models is automatic for a 2.9k-token prefix (write on call one, read on call two).
- Top-level response: `id` (`chatcmpl-...`), `model` (the SERVED model), `created`, `object`, `service_tier` (`default`), `system_fingerprint`, `choices[]`. The `x-request-id` header is a UUID that differs from the body `id`.
- `perplexity/auto` headers observed: `x-perplexity-autoroute-outcome: routed`, `-route: none`, `-confidence: 0.992`, `-effort: low` (effort only because `routing.reasoning_effort` was `auto`). A direct call carries none of them. Rate-limit headers `x-ratelimit-limit-requests: 3`, `-remaining-requests`, `-reset-requests: 1s` (3 requests per second at tier 1).
- Errors, all `{"error": {"code": null, "message", "param", "type": "invalid_request_error"}}`: 402 tier ("The model 'anthropic/claude-opus-5-5' requires usage tier 2 or higher, and your organization is on tier 1. ..."), 404 unknown model, 400 `routing requires model perplexity/auto` (`param: routing`, and it fires before the routes-length check), 400 `routing: model anthropic/claude-opus-5-5 is not available` (a custom route above the tier is a 400, not a 402).

**Contradictions with the epic description**
- The epic says the listing's `pricing` field includes long-context tiers. It does not; only the documentation page does.
- The epic says "perplexity_complete tool" is candidate scope; the owner narrowed it to no tool in this change.
- The listing needs no usage tier parameter: tier filtering is implicit, and the tier is not returned, so it is inferred (D4).

**Existing code this touches** (read, not changed, in this proposal): `usage.py` (`API_FAMILIES` refuses an unknown family at `_build_event`; `_PARSERS` has `agent` and `embeddings` only; Search and Decisions build a `Usage` themselves with `computed_usage`, which stamps the single `PRICES_AS_OF`), `pricing.py` (one date for all tables), `costed.py` (`costed_call`, five callers), `client.py` (`request_json` returns the body only and maps status through `errors.category_for_status`, where 402 is `unexpected_response`).

## Goals / Non-Goals

**Goals:** correct cost accounting for Orchestrator calls (direct and auto-routed) with the same guarantees as the other four APIs (integer nano-USD, unknown rather than guessed, dated table pinned to recorded sources); a tier picture for the account; a client and a costed helper that routing-v2's harness can call in-process.

**Non-Goals**
- **No MCP tool in this change.** The `tools/list` ceilings are 58250, 58550 and 58800 bytes against measured 58245, 58531 and 58765 (`acceptance/tools-list-budget.md`); a twelfth tool, or any `perplexity_models` field, would not fit without trimming other descriptions. A later epic `perplexity_complete` (a tool with `model`, `routing`, and the digest above as output) could take that on once the budget is spent deliberately.
- No Responses (`/responses`) or Messages (`/messages`) formats, no streaming, no `service_tier` selection (`flex` 0.5 times, `priority` 2 times: a request that sets it is not offered by the request builder), no one-hour cache TTL (billed 2 times input; not offered).
- No stored routing facts: `route`, `outcome`, `confidence` and `effort` are returned to the caller but not stored, because `usage_events` has no column for them and this change adds no migration (see Open Questions).
- No change to `perplexity_models`, the model matrix, routing modes or the Decisions classifier.
- No automatic fallback to a model the account can call, and no tier lookup from the 402 message.

## Decisions

**D1. Price from a static dated table, not from the live listing at runtime.** The table follows the repo's pricing discipline: dated constants, a test that pins them to recorded copies of the sources, a live-marked test that re-fetches. The runtime listing is NOT a cost source. Alternative considered: price from the live `pricing` field. Rejected because the field has no long-context rates (so large calls would be silently underpriced, the worst failure for a measuring stick), is unavailable offline, and would make a recorded cost depend on a network call. Cost: a new model Perplexity adds is unpriced (source `none`) until the table is updated; the tier report names such models as unknown so the gap is visible.

**D2. Two sources, each pinning what it is authoritative for.** The documentation page (recorded as `tests/fixtures/orchestrator_models_page.json`, captured by a script from the page's tables, not hand-written) pins ids, tiers, base rates and long-context rates. The recorded listing pins base rates and `cache_write` (the only source for it). The five models the tier 1 listing hides have no `cache_write`, and stay absent (a positive cache-write count on them prices as unknown) instead of being derived from the documentation's "1.25 times input for Anthropic" sentence, which `xai/grok-4.7` already shows is not the whole rule.

**D3. Bill the served model, record the requested one as the preset.** Documentation: "Billing uses that model's published rates" and `model` names the served model. So `usage_events.model` is the response `model` and the cost uses its row, and `preset` stores the requested id (`perplexity/auto` for a routed call). Alternative: store the route name in `preset`. Rejected: the route name is a free string the caller chose and can leak prompt-describing text into the event table.

**D4. Tier range is inferred, not read.** The listing has no tier. The report takes lower bound = highest minimum tier among listed known models, upper bound = lowest unlisted minimum tier minus 1. At tier 1 both are 1; at tier 2 there is no unlisted model so the range is open-ended upward (tier 2 is the highest documented). Alternative: parse "your organization is on tier N" out of a 402. Rejected: the client's rule is never to interpret a message, and it costs a failed call.

**D5. 402 becomes `forbidden`, for this API only.** The 11-value category vocabulary is closed and adding one touches the spec, README and tests; `forbidden` is the existing "this key may not use this model" category (403 for ZDR and org settings means the same to a caller). Globally changing 402 would alter the Agent, Search, Decisions and Embeddings clients, none of which has documented a 402. Mechanism: a per-call status-to-category override passed by the Orchestrator call (`request_json(..., status_categories={402: "forbidden"})`), leaving `category_for_status` untouched.

**D6. Headers via a callback on `request_json`.** `request_json` returns only the body, and the autoroute facts are in the headers. A new optional `on_response` callback receives the successful `httpx2.Response` before the body is returned; the Orchestrator call uses it to capture the headers, every other call is byte-for-byte unchanged. Alternative: return a `(body, headers)` pair for every call. Rejected: it changes every caller.

**D7. Cache reads go to `cache_read_tokens`, cache writes to `cache_creation_tokens`, `cached_tokens` stays null.** The Agent parser stores the API's `cached_tokens` in `cached_tokens`, but for the Orchestrator `cached_tokens` is unambiguously a cache READ with a sibling WRITE bucket, and `cache_read_tokens`/`cache_creation_tokens` already exist as columns with that meaning. Reports that sum `cache_read_tokens` across APIs then mean one thing.

**D8. Unpriceable beats approximate.** Above the long-context threshold with cache writes, no source states the rate; the cost is unknown rather than 1.25 times the long-context input. The same rule makes a missing cache rate, an over-large cache count, or an unknown model unknown. Unknown costs make the usage totals a lower bound, as the system already states.

**D9. The costed helper is not a tool and takes the tool name from its caller.** `run_complete(app, *, tool, project, body)` mirrors `run_search` and `run_decide`; it is a sixth `costed_call` caller with no MCP tool in front of it. It is exercised by tests and by routing-v2's harness. Precedent: `matrix_refresh.probe_request` records tool `model_matrix`, a name no tool owns; the "Event identity fields" requirement is amended to say so.

**D10. Request builder is deliberately small.** `model`, `messages`, `max_tokens`, `reasoning_effort`, `routing`, `prompt_cache_key`. Routing rules (1 to 5 routes, name charset and length, 1,000-byte descriptions, 16,384-byte object, `auto` only, no request effort beside `reasoning_effort: auto`) are validated locally because the API's own messages arrive after a rate-limited round trip and `routing` is the part of the request a caller most often gets wrong. Availability and tier are never checked locally.

## Risks / Trade-offs

- [Price table drifts: Perplexity changes a rate, adds a model, ends a promotional rate (`gemini-3.8-flash` and `3.7-flash` rates apply only through 2026-12-31)] -> the live-marked test re-fetches the page and the listing; the date is stamped on every computed event; the 2026-12-31 expiry is a named task in the docs group and a comment on those two rows.
- [A computed cost cannot be reconciled from a response: there is no cost field] -> acceptance task compares the sum of recorded costs for the probe calls with the Console Billing page for the same window and states the difference; until then the table is "documented", not "verified against billing".
- [Long-context threshold counts total `prompt_tokens`, which is what the documentation says ("when the input is above that range") but no probe crossed it] -> the rule is unit-tested from the documentation's wording; crossing it live costs about $0.06 on `openai/gpt-6-luna` (272k tokens at the above-threshold rate) and is an optional acceptance step, not required.
- [`x-ratelimit-limit-requests: 3` at tier 1: a harness running arms in parallel gets 429s] -> the existing 429 retry honors `Retry-After`; the helper does no concurrency of its own; noted for routing-v2.
- [Unused production code: `run_complete`, the report and the digest have no MCP caller] -> accepted for one release; they are the contract the measuring stick builds on. If no consumer appears in the next release the epic that follows (`perplexity_complete` or a harness) decides, and these stay small (one module).
- [ZDR and organization settings: the listing does not reflect them] -> the report states it and never claims callable; a 403 maps to `forbidden`.
- [The `usage-recording` spec says an event carries an MCP tool name] -> amended in the delta to allow a caller-supplied helper name, as the model-matrix probe already does.

## Migration Plan

No database migration; `usage_events.api` is free text and `usage_json` is already generic, so existing rows and the usage report need no change. Deploy is the normal pm2 restart after merge. Rollback is a revert: Orchestrator events already stored keep their rows (they are ordinary events; a report groups them by `api`). No feature flag.

## Open Questions

- Should the route and outcome of an auto-routed call be stored (a nullable `usage_events` column or an `orchestrator_routes` table)? It would let `perplexity_usage` group spend by route, which routing-v2 may want, but it needs a migration; defer until routing-v2 states what it measures.
- Should a later epic let the runtime listing fill a missing price row (source `computed`, a distinct `price_table` such as `orchestrator-models-live:<date>`) so a brand-new model is priced before the table is updated? Deferrable: it only changes how soon an unknown cost becomes known.
- Reconcile the table against the Console Billing page (see Risks) and, with a tier 2 account, capture `cache_write` for the five hidden models.

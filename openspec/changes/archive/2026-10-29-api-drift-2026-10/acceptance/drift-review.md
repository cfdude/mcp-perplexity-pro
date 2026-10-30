# API drift review, 2026-10-29

Review of Perplexity API changes since the last full verification (2026-10-09 to 2026-10-17).
Sources: the docs changelog (`perplexity-changelog-2026-10-29.md`, fetched 2026-10-29), the effort
and pricing pages, live calls with the project key, and the live server's own model matrix.

## Unchanged (verified live today)
- `GET /v1/models`: shape and prices unchanged for every model we had. The live server's daily
  matrix refresh found exactly two differences from the 2026-10-17 baseline: `openai/gpt-6.1-terra`
  added (probed automatically, source `probe`) and `perplexity/nemotron-3-ultra-550b-a55b` marked
  `removed` (the docs say Nemotron 3.5 Super replaces it).
- Search API response (`id`, `results[title,url,snippet,last_updated]`): same keys as the fixture.
- Decisions API response (`answers`, `model`, `usage`): same keys; a request naming
  `pplx-decider-v1.1-27b` still echoes `pplx-decider-v1.1-27b` (the docs say it now selects v1.2).
  `pplx-decider-flash-v1.2` is accepted.
- Embeddings response (`data[embedding,index,object]`, `model`, `usage.cost`): same keys.

## Changed or new (action needed)
1. **Agent API requires paid credits.** `POST /v1/agent` now answers 403 `The Agent API requires
   paid credits. Add paid credit at https://console.perplexity.ai ... (type: restricted_api_key)`
   for both `preset` and `effort` bodies; models, Search, Decisions and Embeddings still answer.
   Every `perplexity_ask`, `perplexity_chat` and `perplexity_research` call fails until credit is
   added, and live verification of Agent API behaviour is blocked.
2. **`preset` renamed `effort`** (naming only; `preset` stays as a deprecated alias, responses
   return both). We still send `preset`. Not verifiable live until credit is added.
3. **Effort levels changed** (changelog, 2026-10-16 to 2026-10-29): `high` now runs
   `openai/gpt-6.1-terra` (was `gpt-6-sol`; our `catalog.PRESETS` and README say `gpt-6-sol`), `xhigh`
   keeps `anthropic/claude-opus-5-5` with `openai/gpt-6.1-sol` as fallback, `fast` falls back to
   `openai/gpt-5.6-luna`; step budgets and search token limits rose; new level `ultra-preview`; the
   undocumented `ultra` name is removed; `wide-research` selects `xhigh`; `max_steps` up to 500.
   `reasoning.effort` (the model's own reasoning control) is separate from `effort`.
4. **Decisions API models**: `pplx-decider-v1.2` ($0.02 per million input tokens) replaces
   `pplx-decider-v1.1-27b`; new `pplx-decider-flash-v1.2` (4B, $0.01); both accept text and images;
   `pplx-decider-latest` and `pplx-decider-flash-latest` aliases. Our tool only accepts the two old
   names and refuses images; our classifier uses the old default.
5. **Pricing page layout**: a "Billing units" table now sits under "Search API Pricing", which breaks
   `tests/pricing_page.py` (`ValueError: no price in 'Billing units'`, in
   `tests/test_pricing_live.py`); the prices themselves are unchanged. The Decisions table now lists
   the v1.2 and flash models.
6. **New inputs for `media-inputs`**: native document input (PDF, DOC, DOCX, TXT, RTF as `input_file`
   with inline `file_data` or a public HTTPS `file_url`, continued with `previous_response_id`),
   an `image_search` tool, and image input on the Decisions API.
7. Docs-only: many older Anthropic, Google and xAI models were removed from the model docs (the live
   list still carries them), Gemini 4 Argon has introductory pricing through 2026-11-30 ($2.00 in,
   $10.00 out per million tokens), `max_steps` limit, MCP tool approvals (not used by this server).

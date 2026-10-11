# Proposal

## Why

The server holds a growing local history (chats and research reports) that a caller can only read back by id or title. Perplexity's Embeddings API (`POST /v1/embeddings`, models `pplx-embed-v1-0.6b` and `pplx-embed-v1-4b`) turns text into vectors for a few thousandths of a cent per thousand tokens, which makes "find what I already asked or researched about X" a one-call semantic search. It is also the last of the four APIs the 2.0.0 rewrite committed to (`py-embeddings`, after Agent, Search and Decisions), and the first change that stores new kinds of data (vectors) and the second whose API **reports** its cost in the response (after the Agent API). This change adds one tool, `perplexity_embed`, a small local vector store, and a usage parser for the `embeddings` API family.

The API was probed live on 2026-10-11 (23 requests; 23 captures committed as `tests/fixtures/embeddings_*.json`, in `4a359ad`): the response is `{object, data: [{embedding (base64), index, object}], model, usage: {prompt_tokens, total_tokens, cost: {currency, input_cost, total_cost}}}` with **no request id in the body** and a reported cost; `int8` and `binary` vectors decode to exactly `dimensions` bytes and `dimensions / 8` bytes; `dimensions` must be 128 to 1024 for the 0.6b model, 128 to 2560 for the 4b model, and a multiple of 8; a request of 100 inputs of 5000 characters (about 83k tokens) was a 200; an unknown top-level field is accepted and billed; every error is HTTP 400 `{"error": {message, type, code}}` (the documented 422 does not occur); the documentation's "empty string" and "512 inputs" limits are enforced as documented. See `design.md` "Observed shapes".

## What Changes

- Add one tool, `perplexity_embed`, with four actions: `index` (embed and store the caller's saved chats, completed research reports, or caller-supplied texts), `search` (embed a query, rank the stored chunks by similarity, return the best chunks with their text and score), `status` (what is indexed and what is not) and `delete` (remove stored vectors, with `confirm`). **Raw vectors are never returned to the caller.** `index` states plainly in the tool description that the text it indexes is sent to Perplexity. Sources are `chat` (saved chat messages), `job` (completed research reports) and `text` (caller-supplied items).
- Add a local store: one new table `embedding_chunks` (migration `0005`, project-scoped, `ON DELETE CASCADE` to the project and to the chat message or research job a chunk came from, so deleting a chat, a job or a project removes its vectors), vectors stored as `int8` bytes or packed bits (`encoding` `int8` or `binary`), chunk text stored with each vector, no duplicate chunks, re-embedding only what changed, and a per-project cap on stored chunks, and indexes on the foreign keys so cascades stay cheap. Search scores with cosine similarity on `int8` vectors and with Hamming similarity on `binary` ones, in memory with numpy (a new dependency).
- Add `PerplexityClient.embed(body)`, a tolerant response model (`data: list[Any]` required), exact base64 decoding of both encodings with length checks, and a Search-like rule set (never replayed after a response other than 429).
- Record one usage event per Embeddings request that reaches the API through the shared `costed.costed_call`: API family `embeddings`, tool `perplexity_embed`, the response `model`, the token counts, the **reported** cost (a new parser registered in `usage._PARSERS`), falling back to the computed price when the response reports none, and a null request id. An `index` call that needs several batches makes several requests and records several events.
- Validate everything the probe showed locally: model, dimensions per model (a multiple of 8), encoding, input limits (batches of at most 64 chunks and at most 100000 characters, chunks of at most 4000 characters: the character budget keeps a batch inside the 120000-token request limit even for dense text such as CJK or code), query length.
- Out of scope: contextualized embeddings (`/v1/contextualized-embeddings`), returning or exporting vectors, an approximate-nearest-neighbour index, re-ranking, embedding images, indexing the usage log, automatic indexing on every chat turn, cost ceilings.

## Capabilities

### New Capabilities

- `embeddings-client`: the `embed` call, tolerant parsing, retry rules, error mapping, diagnostics and vector decoding.
- `embeddings-store`: the `embedding_chunks` table, migration `0005`, cascades, uniqueness, chunking and the stored-chunk cap.
- `embeddings-tool`: the `perplexity_embed` tool: actions, validation, cost, recording, search ranking and privacy of vectors.

### Modified Capabilities

- `agent-research`: "Job records" (the scenario naming revision 0004 as the head is reworded; nothing else changes).

Checked against the other main specs: `usage-recording` already names API family `embeddings`, the "Reported wins" cost rule and the one-event-per-call contract (this change registers the parser its "Cost source" requirement anticipates); `local-storage` "Versioned migrations" and "Project deletion outcomes" cover a new project-scoped table by introspection; `agent-chat` "Deleting a chat" is unchanged in what it promises (the chat and its messages go) and now also removes their vectors by cascade, which that requirement does not forbid. One main spec goes stale and is MODIFIED: `agent-research` "Job records", whose scenario "Live database upgrades straight to head" names revision 0004 as the head (reworded to name the migrations through 0004).

## Impact

- **Code:** `src/mcp_perplexity_pro/` gains `models/embeddings.py`, `embeddings.py` (validation, chunking, decode, scoring, cost, `run_embed`), `storage/embeddings.py` (row operations), `tools/embeddings.py`, `migrations/versions/0005_embedding_chunks.py`; `storage/models.py` gains `EmbeddingChunk`; `client.py` gains `embed`; `usage.py` gains `usage_from_embeddings_response` and its parser entry; `tools/__init__.py` registers one tool (ten in total).
- **Tests (existing files edited):** `tests/test_server.py` and `tests/test_contract_checks.py` (the sorted tool list, the `costed_call` caller sweep, the category and secrets checks), `tests/test_recording_order.py` (an embed case), `tests/test_wiring_one_event_per_call.py` (an embed call and totals), the migration-head and schema-comparison tests that name `0004` as head (`tests/test_packaging.py`, `tests/test_jobs_migration.py`).
- **Dependencies, settings:** one dependency (`numpy`); no setting.
- **Migration:** `0005` adds a table; the runner takes its usual `backup-0004.db` before upgrading; the downgrade drops the table (and every stored vector).
- **Spend:** a few thousandths of a cent per thousand tokens ($0.004 per million tokens for the 0.6b model, $0.03 for the 4b); an `index` call stops after the item that reaches `limit` new chunks (default 256, at most 2048, plus up to 49 more from the last whole item), so one call costs at most a few cents even at the 4b price; nothing local caps the number of calls. Live acceptance spends well under $0.01.
- **Privacy:** `index` sends chunk text to the Embeddings API (documented in the tool description and README); `search` sends only the query; stored vectors and text stay in the local database.
- **Tool surface:** from nine to ten tools; `tools/list` was 49539 bytes with nine. The design target of about nine is exceeded by one; the growth is measured and the existing descriptions are the lever if it matters.
- **Risks carried forward:** vectors cannot be validated semantically offline (only against recorded vectors); the quality of search is the provider's; a stored vector is tied to its `(model, dimensions, encoding)` and a search only compares like with like.

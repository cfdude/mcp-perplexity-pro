## Purpose

Defines `perplexity_embed`, the tool that indexes a project's saved chats, completed research reports or supplied texts as vectors in the local store and searches them by meaning: its actions and arguments, validation, ranking, what it costs and how every request is recorded.

## ADDED Requirements

### Requirement: Embed tool
The server SHALL provide `perplexity_embed` with an `action` of `index`, `search`, `status` or `delete` and typed parameters. It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` true and `openWorldHint` true. Its description SHALL state that `index` sends the indexed text to Perplexity, that vectors are never returned, the price per million tokens for each model, and that stored vectors belong to a project.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_embed` is present with an output schema, the three annotations, the privacy wording, the prices and the vectors-never-returned wording

#### Scenario: Unknown action
- **WHEN** a client passes action `rebuild`
- **THEN** the call fails with `invalid_request` and nothing is sent or stored

### Requirement: Embedding options
`model` SHALL be `pplx-embed-v1-0.6b` (default) or `pplx-embed-v1-4b`; `dimensions` an optional whole number, a multiple of 8, from 128 to 1024 for the 0.6b model and 128 to 2560 for the 4b model, sent only when given; `encoding` `int8` (default) or `binary`, sent as `base64_int8` or `base64_binary`. The request SHALL always name the model and the encoding. Any other value SHALL fail with `invalid_request` naming the option before any call.

#### Scenario: Defaults and sent options
- **WHEN** a search is made with no options, and separately with the 4b model, 256 dimensions and `binary`
- **THEN** the first request carries the 0.6b model and `base64_int8` and no `dimensions`, and the second carries the 4b model, 256 and `base64_binary`

#### Scenario: Refused options
- **WHEN** a client passes dimensions 64, 130, 2000 with the 0.6b model, 5000, a model `nope`, or encoding `float`
- **THEN** each call fails with `invalid_request` naming the option and nothing is sent

### Requirement: Index sources
`index` SHALL take a `source` of `chats` (every message of the project's chats with non-blank text), `jobs` (every research job of the project that finished with non-blank result text) or `texts` (the caller's `items`). Items given with another source, or a bad `texts` call, SHALL fail with `invalid_request` before any call.

#### Scenario: Chats and jobs
- **WHEN** a project has two chats with messages and one completed research job, and each source is indexed
- **THEN** every non-blank message, and the job's result, become chunks of source `chat` and `job`

### Requirement: Text items
`items` SHALL be 1 to 100 objects, each with a non-blank `key` of at most 128 characters, unique within the call, and a non-blank `text` of at most 100000 characters.

#### Scenario: Texts refused
- **WHEN** `texts` is indexed with no items, a repeated key, a blank text, or 101 items, and separately `chats` is indexed with items
- **THEN** each call fails with `invalid_request` and nothing is sent

### Requirement: Only pending items are embedded
An item SHALL be pending when it has no stored chunk for the call's `(model, dimensions, encoding)` or its stored chunks' hashes differ from its current chunks. `index` SHALL embed only pending items; an item whose chunks all exist SHALL be skipped, spend nothing and be counted as skipped, and a changed item's old chunks for that triple SHALL be replaced by its new ones.

#### Scenario: Repeat index spends nothing
- **WHEN** the same texts are indexed twice
- **THEN** the second call sends no request, records no event and reports every item skipped

#### Scenario: Changed text replaced
- **WHEN** a text key is indexed again with different text
- **THEN** its old chunks are replaced by the new ones and the other items are untouched

### Requirement: Index is bounded and resumable
`index` SHALL embed at most `limit` new chunks per call (default 256, 1 to 2048), whole items first, in batches of at most 64 inputs per upstream request, each batch stored before the next is sent, and SHALL report `remaining`, the pending chunks not embedded, so a caller can call again until it is 0. A text with more than 50 chunks is cut to 50 with a warning.

#### Scenario: Limit and remaining
- **WHEN** a project has 150 pending chunks and `limit` is 100
- **THEN** about 100 chunks are embedded in two requests of at most 64 inputs, `remaining` is the rest, and a second call embeds the rest

#### Scenario: Limit out of range
- **WHEN** a client passes `limit` 0 or 2049
- **THEN** the call fails with `invalid_request` naming `limit` and nothing is sent

### Requirement: A failed batch keeps earlier work
When a request of an `index` call fails or its response cannot be decoded, the error SHALL be raised after the earlier batches were stored and recorded, and its message SHALL say how many chunks were stored first. The failed batch SHALL store nothing and its items SHALL stay pending.

#### Scenario: Second batch fails
- **WHEN** the first of two batches succeeds and the second returns 503
- **THEN** the first batch's chunks are stored, two events exist (`ok` and `upstream_failure`), and the error is `upstream_failure` naming the stored count

#### Scenario: Wrong vector length
- **WHEN** a billed response holds a vector of the wrong length
- **THEN** the call fails with `unexpected_response`, the event is recorded `ok`, and nothing of that batch is stored

### Requirement: Search
`search` SHALL take a non-blank `query` of at most 4000 characters, a `top_k` of 1 to 20 (default 5), an optional `min_score` from -1 to 1 and an optional `source` filter, embed the query in one request with the call's model, dimensions and encoding, rank the project's stored chunks of the same triple, and return the best `top_k` at or above `min_score`, best first.

#### Scenario: Ranking
- **WHEN** three stored chunks have known vectors and the query vector equals the second, is near the first and opposite the third
- **THEN** the hits are ordered second, first, third with scores 1.0, a value below 1.0 and -1.0

#### Scenario: Hit fields
- **WHEN** a search returns a hit
- **THEN** it holds `score`, `source`, its reference (`chat_id` and `message_id`, `job_id` or `key`), `chunk_index` and the chunk text cut to 800 characters

#### Scenario: Filters and limits
- **WHEN** `top_k` is 1, or `min_score` is 0.5, or `source` is `job`
- **THEN** only that many, only chunks at or above that score, or only chunks of that source are returned

#### Scenario: Nothing to compare
- **WHEN** a project has no chunks for the triple
- **THEN** the result has no hits and a warning, and no request is sent and no event is recorded

#### Scenario: Refused query
- **WHEN** the query is blank, over 4000 characters, or `top_k` is 21
- **THEN** the call fails with `invalid_request` and nothing is sent

### Requirement: Scoring
For `int8` the score SHALL be the cosine similarity of the query and the stored vector read as signed 8-bit integers (a zero vector scores 0); for `binary` it SHALL be `1 - hamming distance / dimensions`.

#### Scenario: Cosine and Hamming values
- **WHEN** `int8` vectors `[1, 0]` and `[1, 1]` are compared, and separately binary vectors `0b11110000` and `0b11000000`
- **THEN** the scores are about 0.7071 and 0.75

### Requirement: Vectors are never returned
No result, error, log record or usage event SHALL contain a vector, its base64 text or its bytes.

#### Scenario: Result has no vector
- **WHEN** `index` and `search` return
- **THEN** their structured and text content contain no base64 vector and no field holding vector values

### Requirement: Status
`status` SHALL return, for the project, the stored chunk count per `(source, model, dimensions, encoding)`, the number of chat messages and finished research jobs with text that have no chunk for the call's triple, and SHALL make no request, record no event and create no project.

#### Scenario: Counts
- **WHEN** a project has indexed chats under one triple and some unindexed jobs
- **THEN** `status` lists the stored counts per triple and the unindexed counts

#### Scenario: Unknown project
- **WHEN** `status` names a project that does not exist
- **THEN** it returns empty counts and no project is created

### Requirement: Delete
`delete` SHALL require `confirm` true and remove the project's chunks matching the optional `source` and the call's triple filters, returning the number removed; without `confirm` it SHALL fail with `confirmation_required` and delete nothing.

#### Scenario: Confirmed delete
- **WHEN** `delete` is called with `source` `chat` and `confirm` true
- **THEN** only the chat chunks of that project are removed and their count is returned

#### Scenario: Unconfirmed delete
- **WHEN** `delete` is called without `confirm`
- **THEN** it fails with `confirmation_required` and nothing is removed

### Requirement: Cost of an embedding request
The cost of a request SHALL be the cost the API reports (`usage.cost.total_cost`, converted to nano-USD) with source `reported`; when the response reports none and `prompt_tokens` is a valid count of a priced model, the documented price per token (0.6b: 4 nano-USD; 4b: 30) with source `computed`; otherwise unknown (source `none`), never zero. A reported cost SHALL NOT be replaced by a computed one.

#### Scenario: Reported cost
- **WHEN** the recorded 4b response (12 tokens, `total_cost` 3.6e-07) is returned
- **THEN** the cost is 360 nano-USD with source `reported`

#### Scenario: Computed and unknown cost
- **WHEN** a response has `prompt_tokens` 100 for the 0.6b model and no cost, and separately no usage at all
- **THEN** the first costs 400 nano-USD `computed` and the second is unknown with source `none`

### Requirement: Embed is recorded
Each Embeddings request that reaches the API SHALL be recorded once as a usage event: tool `perplexity_embed`, API family `embeddings`, the response `model`, no request id, the project, latency, token counts and cost. A failed request carries its error category with cost 0 and source `none`; an unparseable 200 is `unexpected_response`; a billed response that fails decoding stays `ok`. `status`, `delete` and refused calls record nothing.

#### Scenario: One event per request
- **WHEN** an `index` call needs two requests, and a search needs one
- **THEN** two events and one event are recorded with tool `perplexity_embed` and API `embeddings`

#### Scenario: Failure and refusal
- **WHEN** a request returns 401, and separately a call is refused locally
- **THEN** the first leaves one `authentication` event with cost 0 and source `none` and the second leaves no event and no project

### Requirement: Recording order, writes and privacy
Each batch SHALL resolve and commit its project before the upstream call, hold no write unit across the call, record the event after it, and only then write its chunks in a write that survives cancellation of the calling task. No text, query or vector SHALL reach a log record or a usage event column, and the configured API key SHALL be replaced by `[redacted]` in returned chunk text.

#### Scenario: Write after the event
- **WHEN** an `index` batch completes
- **THEN** the usage event is stored before the chunk rows and no write unit is open during the request

#### Scenario: Cancelled after the response
- **WHEN** the calling task is cancelled after the response returned
- **THEN** the event and the batch's chunks are still stored

#### Scenario: Key in stored text
- **WHEN** a stored chunk contains the configured key and a `pplx-` shaped example
- **THEN** a search hit shows `[redacted]` for the key and keeps the example

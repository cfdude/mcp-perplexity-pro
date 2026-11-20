## ADDED Requirements

### Requirement: Dated Orchestrator price table
The server SHALL hold a dated table of the 47 Orchestrator models on the documentation page captured 2026-11-19: minimum usage tier, base per-token rates in integer nano-USD (input, output, cache read), the cache-write rate when known, and any long-context rates with threshold and boundary. The table SHALL carry its own date and source, leave an unstated rate absent, and not contain `perplexity/auto`.

#### Scenario: Table equals the recorded documentation page
- **WHEN** the table is compared with the recorded copy of the documentation page's model tables
- **THEN** the id sets are equal and every minimum tier, base rate, long-context threshold and long-context rate equals the page's

#### Scenario: Table equals the recorded listing
- **WHEN** the table is compared with the recorded `GET /orchestrator/v1/models` response (42 models)
- **THEN** every listed model is in the table and its base rates and its cache-write rate (or the absence of one) equal the response's `pricing` converted to nano-USD per token

#### Scenario: Cache write comes from the listing only
- **WHEN** a model is absent from the recorded listing (the five tier 2 models)
- **THEN** its cache-write rate is absent from the table

#### Scenario: Auto is not priced
- **WHEN** the table is searched for `perplexity/auto`
- **THEN** it is not there

### Requirement: Cost from tokens
The server SHALL compute one call's cost as exact integer nano-USD from the served model's row: fresh input (`prompt_tokens` minus cache reads minus cache writes) at the input rate, cache reads and writes at their rates, and all `completion_tokens` (reasoning included) at the output rate. A call whose `prompt_tokens` is above a row's long-context threshold SHALL use that row's long-context rates throughout. An absent cache count is 0.

#### Scenario: Plain call
- **WHEN** `openai/gpt-6-luna` serves 12 prompt and 5 completion tokens with no cache figures
- **THEN** the cost is 3700 nano-USD

#### Scenario: Cache write
- **WHEN** the recorded first call (2869 prompt, 5 completion, 2866 cache-write tokens) is priced for `openai/gpt-6-luna`
- **THEN** the cost is 3 tokens at 100, 2866 at 125 and 5 at 500, that is 361,050 nano-USD

#### Scenario: Cache read
- **WHEN** the recorded repeat call (2869 prompt, 5 completion, 2866 cached tokens) is priced for `openai/gpt-6-luna`
- **THEN** the cost is 3 tokens at 100, 2866 at 10 and 5 at 500, that is 31,460 nano-USD

#### Scenario: Reasoning tokens are not charged twice
- **WHEN** a call reports 100 completion tokens of which 80 are reasoning tokens
- **THEN** the output charge is for 100 tokens, not 180

#### Scenario: Above the long-context threshold
- **WHEN** `openai/gpt-6.1-sol` serves 300,000 prompt and 1,000 completion tokens with no cache figures
- **THEN** input and output are charged at the documented rates above 272k, not the base rates

#### Scenario: Boundary
- **WHEN** a call has exactly 272,000 prompt tokens on an OpenAI model and exactly 200,000 on `xai/grok-4.7`
- **THEN** the first is charged at the base rates and the second at the long-context rates, because the page writes `<=272k`/`>272k` for OpenAI and `<200k`/`>=200k` for xAI

### Requirement: Unpriceable calls are unknown
The cost SHALL be unknown (never guessed, never a default rate) when the model has no row, `prompt_tokens` or `completion_tokens` is missing or not a valid count, a positive cache count has no rate, the cache counts exceed `prompt_tokens`, or a call above the long-context threshold has a positive cache-write count (the page gives no such rate). The helper SHALL never raise.

#### Scenario: Unpriceable long-context cache write
- **WHEN** a call above the threshold has a positive cache-write count
- **THEN** the cost is unknown and the token counts are still recorded

#### Scenario: Missing rate
- **WHEN** `perplexity/kimi-k3` (no cache-write rate) serves a call with a positive cache-write count
- **THEN** the cost is unknown, and with a zero cache-write count it is priced normally

#### Scenario: Unknown model
- **WHEN** the served model is not in the table
- **THEN** the cost is unknown

#### Scenario: Never raises
- **WHEN** the counts are booleans, negative, strings or above 10^12, or the model is not text
- **THEN** the helper returns unknown without raising

### Requirement: Minimum usage tier per model
The table SHALL record each model's minimum usage tier as the documentation states it: Google, xAI and open-weight models tier 0; OpenAI models and most Anthropic models tier 1; `anthropic/claude-opus-5`, `anthropic/claude-opus-5-5` and the three `anthropic/claude-fable-5*` models tier 2.

#### Scenario: Tiers match the page
- **WHEN** the table is compared with the recorded documentation page
- **THEN** every model's minimum tier equals the page's tier column

### Requirement: Tier-aware listing report
The client SHALL provide `GET /orchestrator/v1/models`, parsed tolerantly (`data` a required list; an entry without a text `id` skipped and logged). A pure, network-free report over a listing and the table SHALL state the callable ids, the documented ids not callable, the listed ids the table lacks, and the implied tier range (lower: highest minimum tier among listed known models; upper: lowest unlisted minimum tier minus 1).

#### Scenario: Recorded listing, tier 1 account
- **WHEN** the report is built from the recorded 42-model listing
- **THEN** the callable set is those 42, the five tier 2 models are reported as not callable, no model is unknown, and the tier is exactly 1

#### Scenario: New model
- **WHEN** the listing holds a model id the table lacks
- **THEN** it is reported as unknown to the table, and a call to it records an unknown cost

#### Scenario: Higher tier account
- **WHEN** the listing also holds the five tier 2 models
- **THEN** the lower bound is 2 and there is no upper bound

#### Scenario: Zero data retention is not implied
- **WHEN** the report names the callable ids
- **THEN** it states that the listing ignores zero data retention and organization model settings, so a listed model may still return 403

#### Scenario: Auto absent
- **WHEN** the recorded listing is read
- **THEN** `perplexity/auto` is not in it and the report does not list it as missing

#### Scenario: Malformed entry
- **WHEN** a listing entry has no `id` or a non-text one
- **THEN** it is skipped and logged and the other entries are reported

### Requirement: No tool exposes the report
No MCP tool SHALL expose the listing or the report.

#### Scenario: Tool surface
- **WHEN** the server lists its tools
- **THEN** none returns Orchestrator listing or tier data

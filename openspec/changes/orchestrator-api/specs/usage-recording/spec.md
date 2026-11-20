## MODIFIED Requirements

### Requirement: Event identity fields
Each event SHALL carry the UTC time it was recorded, the MCP tool name (or, for a call made by a helper that no tool owns, the name its caller supplies), the API family (`agent`, `search`, `embeddings`, `decisions` or `orchestrator`), the resolved model and the requested preset when known, the upstream request or response id when given, a status, the call latency in milliseconds, and the project it was made for (a reference and the project's name at that time) or none. The status SHALL be `ok` or a category of the server's closed error vocabulary.

#### Scenario: Preset and resolved model both kept
- **WHEN** an Agent call requested preset `fast` and the response named model `openai/gpt-6-luna`
- **THEN** the event holds preset `fast` and model `openai/gpt-6-luna`

#### Scenario: Unknown family refused
- **WHEN** a caller records an event with an API family outside the five values
- **THEN** no event is stored and the problem is logged, without raising

#### Scenario: Orchestrator family accepted
- **WHEN** a caller records an event with API family `orchestrator`
- **THEN** the event is stored with that family

#### Scenario: Unknown status refused
- **WHEN** a caller records an event with a status that is neither `ok` nor an error category
- **THEN** no event is stored and a redacted problem is logged, without raising

#### Scenario: Call without a project
- **WHEN** a tool that takes no project makes a costed call
- **THEN** the event has no project reference and no project name

#### Scenario: Refused project name
- **WHEN** the recorder is given a project name that fails the project-name rule
- **THEN** the event is stored with no project reference and no project name, a redacted warning is logged, and nothing is raised

## ADDED Requirements

### Requirement: Orchestrator usage parsing
The recorder SHALL parse the `usage` object of an Orchestrator Chat Completions response for API family `orchestrator`: `prompt_tokens` is input, `completion_tokens` output, `total_tokens` total, `prompt_tokens_details.cached_tokens` cache read (`cache_read_tokens`), `.cache_write_tokens` cache write (`cache_creation_tokens`), `completion_tokens_details.reasoning_tokens` reasoning. A raw mapping has cost source `none`; overlapping figures are never netted; a malformed part is unknown alone.

#### Scenario: Recorded cache-write response
- **WHEN** the recorded usage of the first call of a repeated 2869-token prompt is parsed
- **THEN** input is 2869, output 5, total 2874, cache creation 2866, cache read 0 and reasoning 0, with cost source `none`

#### Scenario: Recorded cache-read response
- **WHEN** the recorded usage of the repeat call is parsed
- **THEN** input is 2869, cache read 2866 and cache creation 0

#### Scenario: Malformed details
- **WHEN** `prompt_tokens_details` is a list and `completion_tokens` is `"5"`
- **THEN** parsing returns normally, the cache figures and the output count are unknown, `prompt_tokens` and `total_tokens` are kept, and each problem is logged

### Requirement: Orchestrator cost is computed from tokens at the served model
A costed Orchestrator call SHALL be recorded with a cost computed from its token counts and the documented per-token prices of the model that SERVED it (the response `model`), source `computed`, stamped with the date of the Orchestrator price table. A call routed by `perplexity/auto` SHALL be priced at the routed model. An unpriceable call SHALL be recorded with cost 0 and source `none`, never at a default or at the requested name.

#### Scenario: Routed call priced at the served model
- **WHEN** a call with request model `perplexity/auto` returns `model` `openai/gpt-6-luna` with 12 prompt and 5 completion tokens, none cached
- **THEN** the event model is `openai/gpt-6-luna` and its cost is 3700 nano-USD with source `computed` and the Orchestrator price-table date

#### Scenario: Unknown served model
- **WHEN** the response names a model absent from the price table
- **THEN** the event is stored with cost 0 and source `none`, and its tokens are kept

#### Scenario: Failed call
- **WHEN** an Orchestrator call fails with HTTP 402
- **THEN** one event exists with status `forbidden`, cost 0 and source `none`

#### Scenario: Recorded once
- **WHEN** the same successful response id is recorded twice
- **THEN** one event exists for it

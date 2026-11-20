## ADDED Requirements

### Requirement: Chat completion call
The client SHALL provide one Orchestrator operation, `POST /orchestrator/v1/chat/completions` on the configured base address with a JSON body and the same bearer credential, non-streaming only, returning the parsed response together with the response headers. It SHALL use the general read timeout (the Orchestrator has no documented long synchronous mode) and SHALL NOT set `stream`.

#### Scenario: Direct call
- **WHEN** the API answers with the recorded `openai/gpt-6-luna` response
- **THEN** the client returns a response whose `model`, `id`, message content `ok` and usage (12 prompt, 5 completion tokens) match that body

#### Scenario: Base address honored
- **WHEN** `PERPLEXITY_BASE_URL` points at a test address
- **THEN** the request goes to that address with the path `/orchestrator/v1/chat/completions`

### Requirement: Local request validation
The request builder SHALL accept only `model`, `messages`, `max_tokens`, `reasoning_effort`, `routing` and `prompt_cache_key`, and SHALL refuse a malformed request before anything is sent (`invalid_request`, nothing billed). It SHALL NOT check whether a model exists or is available at the account's tier: the API decides that.

#### Scenario: Valid routing object
- **WHEN** the recorded custom routing request (default `openai/gpt-6-luna`, one route `code_review`) is built
- **THEN** the body equals the recorded request body

#### Scenario: Basic fields refused
- **WHEN** `model` is empty, `messages` is not a non-empty list of mappings with a `role` and `content`, or `max_tokens` is not a positive integer
- **THEN** `invalid_request` is raised naming the field and no HTTP request is made

#### Scenario: Routing needs auto
- **WHEN** `routing` is given with a model other than `perplexity/auto`, or `routing.default_model` is missing, not text or `perplexity/auto`
- **THEN** `invalid_request` is raised naming the field and no HTTP request is made

#### Scenario: Routes refused
- **WHEN** `routing.routes` is not a list of 1 to 5 entries, a route name is not 1 to 64 characters of letters, digits, `_`, `-` or `.`, equals `none` or repeats, a description is empty or over 1,000 UTF-8 bytes, or a route model is missing, not text or `perplexity/auto`
- **THEN** `invalid_request` is raised naming the field and no HTTP request is made

#### Scenario: Unknown keys and size refused
- **WHEN** `routing` or a route has an unknown key, or the serialized `routing` is over 16,384 bytes
- **THEN** `invalid_request` is raised and no HTTP request is made

#### Scenario: Effort rules
- **WHEN** `routing.reasoning_effort` is anything but `"auto"`, or a request `reasoning_effort` is set beside `routing.reasoning_effort` `"auto"`
- **THEN** `invalid_request` is raised and no HTTP request is made

#### Scenario: Availability is not checked locally
- **WHEN** a route names `anthropic/claude-opus-5-5`
- **THEN** the request is sent as built and the API's 400 is returned

### Requirement: Response digest
The digest of a response SHALL be total (never raise) and SHALL return the served `model`, the response `id`, the first choice's `finish_reason` and message `content` as received, and the `usage` mapping as received. A null `content` stays null.

#### Scenario: Direct response
- **WHEN** the recorded direct response is digested
- **THEN** the model is `openai/gpt-6-luna`, the content `ok`, the finish reason `stop` and the usage has 12 prompt and 5 completion tokens

#### Scenario: Length with null content
- **WHEN** a response has `finish_reason` `length` and `content` null, as a reasoning model that spent its output budget returns
- **THEN** both are returned as received

#### Scenario: Unreadable body
- **WHEN** the body is not a mapping or has no `choices`
- **THEN** the digest returns nulls for what it cannot read and does not raise

### Requirement: Autoroute header facts
The digest SHALL also return the facts of the `x-perplexity-autoroute-*` response headers: `outcome` (`routed`, `media_input`, `fallback` or `single_model`), `route` (only when routed), `confidence` (a number, only when routed and given) and `effort` (`low`, `medium`, `high` or `default`, only when `routing.reasoning_effort` was `auto`). An absent header SHALL be null, never an empty string, and an unrecognized `outcome` or `effort` SHALL be kept as received.

#### Scenario: Recorded auto-routed response
- **WHEN** the recorded `perplexity/auto` response with its headers is digested
- **THEN** outcome is `routed`, route `none`, confidence 0.992, effort `low` and the model `openai/gpt-6-luna`

#### Scenario: Direct call has no routing facts
- **WHEN** the recorded direct response is digested
- **THEN** outcome, route, confidence and effort are all null

#### Scenario: Unrecognized value kept
- **WHEN** a header carries an outcome the server does not know
- **THEN** it is returned as received

### Requirement: Orchestrator error mapping
Orchestrator failures SHALL map by HTTP status to the existing categories and keep the API's message, redacted, as `api_message`. For this API only, 402 SHALL map to `forbidden`; the category vocabulary SHALL NOT grow, the mapping of 402 for the other APIs SHALL NOT change, and the client SHALL NOT interpret a message.

#### Scenario: Tier 402
- **WHEN** the API returns the recorded 402 for `anthropic/claude-opus-5-5`
- **THEN** `forbidden` is raised with status 402 and a message that includes `requires usage tier 2 or higher`

#### Scenario: Unknown model
- **WHEN** the API returns the recorded 404 for `perplexity/not-a-model`
- **THEN** `not_found` is raised whose message includes `Invalid model`

#### Scenario: Routing 400s
- **WHEN** the API returns the recorded 400s (routing with a model other than auto; a route naming a model above the tier)
- **THEN** each raises `invalid_request` carrying the API's message

#### Scenario: Other statuses
- **WHEN** the API returns 401, 403, 429 or 503
- **THEN** the categories are `authentication`, `forbidden`, `rate_limited` and `upstream_failure`

#### Scenario: Other APIs unchanged
- **WHEN** another API's client call receives HTTP 402
- **THEN** the category is the one it was before this change (`unexpected_response`)

### Requirement: A billed POST is not replayed
An Orchestrator chat completion SHALL follow the billed-POST rule of every other costed call: retried after a connect failure and after a 429 (never billed; waiting for `Retry-After` within the configured maximum, which matters at the tier 1 limit of 3 requests per second), and not retried after any other response or after a timeout once sent.

#### Scenario: 5xx and timeout
- **WHEN** a request returns 503, and separately its read times out
- **THEN** `upstream_failure` and `network_timeout` are raised, each after exactly one request

#### Scenario: Rate limited then served
- **WHEN** a request returns 429 with `Retry-After: 1` and then the recorded response
- **THEN** the client waits at least 1 second and returns the response after two requests

### Requirement: Costed call helper
The server SHALL provide a helper that makes one Orchestrator chat completion through the one costed-call sequence under a tool name its caller supplies, API family `orchestrator`, and returns the digest, the cost fields and the recorded status. It SHALL add no second `record_usage` call site.

#### Scenario: Auto call recorded
- **WHEN** the helper runs the recorded `perplexity/auto` call under tool name `routing_arm`
- **THEN** one event exists with tool `routing_arm`, API `orchestrator`, model `openai/gpt-6-luna`, preset `perplexity/auto`, the response `id` as request id, status `ok`, source `computed` and cost 3700 nano-USD

#### Scenario: Failure recorded
- **WHEN** the call fails with the recorded 402
- **THEN** one event exists with status `forbidden`, cost 0 and source `none`, and the error is raised

### Requirement: Unreadable responses are still recorded
A 200 whose `usage` has no valid `prompt_tokens` and `completion_tokens` SHALL be recorded `unexpected_response` with unknown cost and raise `unexpected_response`; a 200 with valid counts but no readable choices SHALL be recorded `ok` (it was billed) and return the digest's nulls.

#### Scenario: Unreadable usage
- **WHEN** a 200 body has no `usage`
- **THEN** one event exists with status `unexpected_response`, cost 0 and source `none`, and `unexpected_response` is raised

#### Scenario: Billed without choices
- **WHEN** a 200 body has valid usage counts and no `choices`
- **THEN** one event exists with status `ok` and a computed cost, and the digest fields are null

### Requirement: No MCP tool
The change SHALL NOT register a new MCP tool or change the schema, description or output of an existing one. The listed tool names SHALL stay the eleven of the current release, and the size of the `tools/list` response SHALL stay within the existing ceilings of `tests/test_tools_list_budget.py`.

#### Scenario: Tool list unchanged
- **WHEN** the server lists its tools
- **THEN** the names are the same eleven and no `tools/list` ceiling in the budget test has been raised

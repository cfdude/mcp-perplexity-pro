# Spec Delta

## MODIFIED Requirements

### Requirement: Model
`model` SHALL be `pplx-decider-v1.1-27b` (the default), `pplx-decider-v1-27b`, `pplx-decider-v1.2`, `pplx-decider-flash-v1.2`, `pplx-decider-latest`, `pplx-decider-flash-latest`, `perplexity/pplx-decider-latest` or `perplexity/pplx-decider-flash-latest`, and the request SHALL always name it. Any other value SHALL fail with `invalid_request` naming `model` before any call.

#### Scenario: Default model
- **WHEN** a client passes no `model`
- **THEN** the request carries `pplx-decider-v1.1-27b`

#### Scenario: Older model and unknown model
- **WHEN** a client passes `pplx-decider-v1-27b`, and separately `pplx-decider-nope`
- **THEN** the first request carries it and the second call fails with `invalid_request` naming `model`

#### Scenario: Newer models and aliases
- **WHEN** a client passes each of `pplx-decider-v1.2`, `pplx-decider-flash-v1.2`, `pplx-decider-latest`, `pplx-decider-flash-latest`, `perplexity/pplx-decider-latest` and `perplexity/pplx-decider-flash-latest`
- **THEN** each request carries the name it was given

### Requirement: Cost of a decision
The cost of a request SHALL be its input tokens at the documented price of the model it names ($0.02 per million for every accepted model except the flash models, `pplx-decider-flash-v1.2`, `pplx-decider-flash-latest` and `perplexity/pplx-decider-flash-latest`, at $0.01; output tokens are free; no per-request fee), whatever the question count, with source `computed`. When `input_tokens` is missing or not a non-negative whole number the cost SHALL be unknown (`cost_usd` null, source `none`), never zero. The result carries `cost_usd` as an exact decimal string.

#### Scenario: Recorded request
- **WHEN** the recorded three-question response (347 input tokens) is returned
- **THEN** the result has `cost_usd` `"0.00000694"` and `cost_source` `computed`

#### Scenario: A flash model
- **WHEN** a request naming `pplx-decider-flash-v1.2` gets a response reporting 347 input tokens
- **THEN** the result has `cost_usd` `"0.00000347"` and the event cost 3470 nano-USD, source `computed`

#### Scenario: The request's name prices the call
- **WHEN** a request names `pplx-decider-flash-latest` and the response echoes `pplx-decider-flash-v1.2` (or another name, or none)
- **THEN** the cost is priced at the flash rate by the request's name, and the event records the response's model when present

#### Scenario: Unreadable usage
- **WHEN** a response carries no `usage`, or an `input_tokens` that is a boolean, negative, a float or a string
- **THEN** the call succeeds with `cost_usd` null and `cost_source` `none`, and the event has cost 0 and source `none`

#### Scenario: Output tokens missing
- **WHEN** `usage` holds a valid `input_tokens` and no `output_tokens`
- **THEN** the cost is computed from the input tokens, `output_tokens` is null and the call does not fail

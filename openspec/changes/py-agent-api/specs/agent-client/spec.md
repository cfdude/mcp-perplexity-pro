# Spec Delta

## Purpose

Defines how the client talks to the Perplexity Agent API: creating, fetching and cancelling a run, parsing its responses tolerantly, the longer read timeout for synchronous runs, and how the Agent endpoints' failures map onto the server's error categories.

## ADDED Requirements

### Requirement: Create, fetch and cancel a run
The client SHALL provide three operations on the Agent API: create a run (`POST /v1/agent`), fetch a run by its response id (`GET /v1/agent/{id}`) and cancel a run (`POST /v1/agent/{id}/cancel`). Create and fetch return a run; cancel returns the response id and the status the API reports.

#### Scenario: Create a synchronous run
- **WHEN** the API answers a create request with the recorded fast-preset response
- **THEN** the client returns a run whose `id`, status `completed`, `model`, `output` and `usage` match that response

#### Scenario: Fetch a finished run
- **WHEN** the API answers a fetch with the recorded completed background snapshot
- **THEN** the client returns a run with status `completed` and a final `message` output item

#### Scenario: Cancel a run
- **WHEN** the API answers a cancel with the recorded `cancelling` response
- **THEN** the client returns that response id and status `cancelling`

### Requirement: Response ids are checked before use
A response id placed in a request path SHALL consist of `resp_` followed by 1 to 100 letters, digits, hyphens or underscores. Any other value SHALL fail with `invalid_request` before any request is sent.

#### Scenario: Path injection refused
- **WHEN** a fetch or cancel is attempted with the id `resp_x/../../v1/models`
- **THEN** the client raises `invalid_request` and no request is sent

#### Scenario: Recorded id accepted
- **WHEN** a fetch uses the id of the recorded completed snapshot
- **THEN** the request is sent to `/v1/agent/` followed by that id

### Requirement: Tolerant run parsing
A run SHALL be parsed with every unknown field and unknown output item type retained, and only `id` and `status` required. An absent `output` is an empty list; an absent or null `usage`, `model` and `error` stay absent. A response lacking a required field SHALL raise `unexpected_response` naming the endpoint and the field.

#### Scenario: Unknown output item
- **WHEN** a response carries an output item of a type the client has no definition for
- **THEN** parsing succeeds and the item is retained as received

#### Scenario: Queued run without usage
- **WHEN** the API returns the recorded queued submit response (`usage` null, `output` empty)
- **THEN** the client returns a run with status `queued`, no usage and an empty output

#### Scenario: Missing status
- **WHEN** a create response has no `status`
- **THEN** the client raises `unexpected_response` naming `/v1/agent` and `status`

### Requirement: Read timeout for synchronous runs
A create request for a run that is not a background run SHALL use the agent read timeout (`PERPLEXITY_AGENT_READ_TIMEOUT`, default 120 seconds) as its read and write timeout. Every other Agent API call SHALL use the general read timeout. A timeout error SHALL state the timeout that elapsed and its value.

#### Scenario: Synchronous create
- **WHEN** a create request without `background` is sent
- **THEN** the request carries a 120-second read timeout while the general read timeout stays 60 seconds

#### Scenario: Background submit, fetch and cancel
- **WHEN** a create request with `background` true, a fetch and a cancel are sent
- **THEN** each carries the general read timeout

#### Scenario: Synchronous run times out
- **WHEN** a synchronous create exceeds its read timeout
- **THEN** the client raises `network_timeout` stating a read timeout of 120 seconds and sends no second request

### Requirement: Retry rules apply to Agent calls
Creating and cancelling a run SHALL follow the create-request rule: never replayed after an HTTP response other than 429, and never after a timeout once the request was sent. Fetching a run SHALL follow the read rule: retried on 5xx, timeouts and connection failure.

#### Scenario: 5xx on create
- **WHEN** a create request returns 503
- **THEN** the client raises `upstream_failure` after exactly one request

#### Scenario: 5xx on cancel
- **WHEN** a cancel request returns 503
- **THEN** the client raises `upstream_failure` after exactly one request

#### Scenario: 5xx on fetch
- **WHEN** a fetch returns 503 and then the recorded completed snapshot
- **THEN** the client returns the completed run after two requests

### Requirement: Agent error mapping
Agent API failures SHALL map by HTTP status to the existing categories and keep the API's message, redacted: 400 is `invalid_request` whatever the error `type` (`invalid_request`, `invalid_parameter` or `invalid_model`), 404 is `not_found`. The client SHALL NOT interpret a message: a cancel of an unknown run and a cancel of a finished run return the same `400` body and both surface as `invalid_request`.

#### Scenario: Validation message passes through
- **WHEN** the API returns 400 with type `invalid_parameter` for an invalid JSON schema
- **THEN** the client raises `invalid_request` whose message includes the API's text

#### Scenario: Unknown run
- **WHEN** a fetch of a well-formed unknown id returns the recorded 404 body
- **THEN** the client raises `not_found`

#### Scenario: Ambiguous cancel failure
- **WHEN** a cancel returns the recorded unknown-id 400 and another returns the recorded already-finished 400
- **THEN** both raise `invalid_request` with identical messages

### Requirement: Agent call diagnostics
Each Agent API call SHALL be logged like any upstream call: method, path, status, the upstream request id from the `x-request-id` header when present, attempt and elapsed time, and never the request or response body.

#### Scenario: Request id logged
- **WHEN** a create call completes with the recorded response headers
- **THEN** one log record carries `/v1/agent`, status 200 and the `x-request-id` value, and contains no query text

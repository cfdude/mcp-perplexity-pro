## Purpose

Defines how the client talks to the Perplexity Decisions API: sending a decision request, parsing its response tolerantly, the retry rules for a billed POST, how its error bodies map onto the server's error categories, and the diagnostics logged for each call.

## ADDED Requirements

### Requirement: Decide call
The client SHALL provide one Decisions operation, `POST /v1/decisions` (exactly that path: a trailing slash is a 404) with a JSON request body, returning the parsed response: the echoed `model`, the `answers` and the `usage`. It SHALL use the general read timeout and the same bearer credential as every other call.

#### Scenario: Decide succeeds
- **WHEN** the API answers with the recorded three-question response
- **THEN** the client returns a response whose `model`, three `answers` and `usage` (347 input tokens, 3 output tokens) match that body

#### Scenario: General timeout
- **WHEN** a decision request is sent
- **THEN** it carries the general read timeout of 60 seconds

### Requirement: Tolerant decisions parsing
A decisions response SHALL be parsed with every unknown field kept. Only `answers`, an object, is required; each answer, `model` and `usage` are kept as received whatever their type, so a billed 200 is never lost to a schema quibble. A response without `answers`, or with `answers` not an object, SHALL raise `unexpected_response` naming `/v1/decisions` and `answers`.

#### Scenario: Unknown fields kept
- **WHEN** a response carries a top-level extra field and an answer carries an extra field
- **THEN** parsing succeeds and both are retained as received

#### Scenario: Odd values kept
- **WHEN** a response has `usage` null and an answer that is a string
- **THEN** parsing succeeds and both are retained as received

#### Scenario: Missing answers
- **WHEN** a response body is `{"model": "x"}`
- **THEN** the client raises `unexpected_response` naming `/v1/decisions` and `answers`

#### Scenario: Answers not an object
- **WHEN** a response body is `{"answers": [1]}`
- **THEN** the client raises `unexpected_response` naming `/v1/decisions` and `answers`

### Requirement: Decision requests are not replayed
A decision request is a billed POST. The client SHALL NOT retry it after an HTTP response other than 429, nor after a timeout once the request was sent, and SHALL retry it after a connect failure and after a 429, waiting for `Retry-After` when given.

#### Scenario: 5xx on decide
- **WHEN** a decision request returns 503
- **THEN** the client raises `upstream_failure` after exactly one request

#### Scenario: Read timeout
- **WHEN** a decision request is sent and its read times out
- **THEN** the client raises `network_timeout` and exactly one request was sent

#### Scenario: Rate limited then served
- **WHEN** a decision returns 429 with `Retry-After: 1` and then the recorded response
- **THEN** the client waits at least 1 second and returns the response after two requests

### Requirement: Decisions error mapping
Decisions API failures SHALL map by HTTP status to the existing categories and keep the API's message, redacted: every validation failure is HTTP 400 and is `invalid_request` whatever the error `type` (`invalid_request` or `invalid_request_error`); 401 is `authentication`. The error SHALL carry the API's message as `api_message`. The client SHALL NOT interpret a message.

#### Scenario: Validation message passes through
- **WHEN** the API returns the recorded 400 for 129 questions
- **THEN** the client raises `invalid_request` whose message includes `Each request needs between 1 and 128 questions`

#### Scenario: Model message passes through
- **WHEN** the API returns the recorded 400 for an unknown model
- **THEN** the client raises `invalid_request` whose message includes `Invalid model`

#### Scenario: Bad credential
- **WHEN** the API returns the recorded 401
- **THEN** the client raises `authentication` and the message contains no credential

#### Scenario: Echoed key
- **WHEN** a 400 body echoes a string shaped like an API key
- **THEN** the raised error contains a redaction marker in its place

### Requirement: Decide call diagnostics
Each Decisions API call SHALL be logged like any upstream call: method, path, status, the upstream request id from the `x-request-id` header when present, attempt and elapsed time, and never the request body (the state and the questions) or the response body.

#### Scenario: Request id logged
- **WHEN** a decision completes with the recorded response headers
- **THEN** one log record carries `/v1/decisions`, status 200 and the `x-request-id` value, and contains none of the state text

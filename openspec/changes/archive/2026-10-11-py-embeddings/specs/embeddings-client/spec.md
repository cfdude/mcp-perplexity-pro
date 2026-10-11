## Purpose

Defines how the client talks to the Perplexity Embeddings API: sending an embeddings request, parsing its response tolerantly, decoding the base64 vectors exactly, the retry rules for a billed POST, error mapping and diagnostics.

## ADDED Requirements

### Requirement: Embed call
The client SHALL provide one Embeddings operation, `POST /v1/embeddings` with a JSON body, returning the parsed response: the `data` list, the `model` and the `usage`. It SHALL use the general read timeout and the same bearer credential as every other call.

#### Scenario: Embed succeeds
- **WHEN** the API answers with the recorded two-input response for the 4b model
- **THEN** the client returns a response whose `model`, two `data` entries (indexes 0 and 1) and `usage` (12 prompt tokens) match that body

#### Scenario: General timeout
- **WHEN** an embeddings request is sent
- **THEN** it carries the general read timeout of 60 seconds

### Requirement: Tolerant embeddings parsing
An embeddings response SHALL be parsed with every unknown field kept. Only `data`, a list, is required; its items, `model` and `usage` are kept as received whatever their type, so a billed 200 is never lost to a schema quibble. A response without `data`, or with `data` not a list, SHALL raise `unexpected_response` naming `/v1/embeddings` and `data`.

#### Scenario: Unknown fields kept
- **WHEN** a response carries an extra top-level field and an extra field in a data item
- **THEN** parsing succeeds and both are retained as received

#### Scenario: Missing data
- **WHEN** a response body is `{"model": "x"}`, and separately `{"data": {"a": 1}}`
- **THEN** each raises `unexpected_response` naming `/v1/embeddings` and `data`

### Requirement: Embedding requests are not replayed
An embeddings request is a billed POST. The client SHALL NOT retry it after an HTTP response other than 429, nor after a timeout once the request was sent, and SHALL retry it after a connect failure and after a 429, waiting for `Retry-After` when given.

#### Scenario: 5xx and timeout
- **WHEN** an embeddings request returns 503, and separately its read times out
- **THEN** the client raises `upstream_failure` and `network_timeout` respectively, each after exactly one request

#### Scenario: Connect failure then served
- **WHEN** the first connection attempt fails and the second succeeds
- **THEN** the client returns the response after two attempts

#### Scenario: Rate limited then served
- **WHEN** a request returns 429 with `Retry-After: 1` and then the recorded response
- **THEN** the client waits at least 1 second and returns the response after two requests

### Requirement: Embeddings error mapping
Embeddings API failures SHALL map by HTTP status to the existing categories and keep the API's message, redacted: every validation failure is HTTP 400 (the documented 422 does not occur) and is `invalid_request`; 401 is `authentication`. The error SHALL carry the API's message as `api_message`. The client SHALL NOT interpret a message.

#### Scenario: Messages pass through
- **WHEN** the API returns the recorded 400 for 513 inputs, and separately for dimensions 2000 on the 0.6b model
- **THEN** the client raises `invalid_request` whose message includes `input array exceeds maximum of 512 items` and `must not exceed 1024` respectively

#### Scenario: Bad credential and echoed key
- **WHEN** the API returns the recorded 401, and separately a 400 whose message echoes a key-shaped string
- **THEN** the first raises `authentication` with no credential in its message and the second's message holds a redaction marker in place of the string

### Requirement: Embed call diagnostics
Each Embeddings API call SHALL be logged like any upstream call: method, path, status, the `x-request-id` header when present, attempt and elapsed time, and never the request body (the texts) or the response body (the vectors).

#### Scenario: Request id logged
- **WHEN** an embeddings request completes with the recorded response headers
- **THEN** one log record carries `/v1/embeddings`, status 200 and the `x-request-id` value, and contains none of the input text and no base64 vector

### Requirement: Exact vector decoding
A vector SHALL be decoded from its base64 string with strict validation. For `int8` the decoded bytes SHALL number exactly `dimensions`; for `binary` exactly `dimensions / 8` with `dimensions` a multiple of 8. Invalid base64 or any other length SHALL raise `unexpected_response`. The decoder SHALL return the bytes unchanged and SHALL NOT log them.

#### Scenario: Recorded vectors decode to their sizes
- **WHEN** the recorded default 0.6b, 4b default, 256-dimension 4b and 256-dimension binary responses are decoded with their dimensions and encodings
- **THEN** the sizes are 1024, 2560, 256 and 32 bytes respectively

#### Scenario: Wrong length or bad base64
- **WHEN** a vector decodes to one byte too few, or its string is not valid base64, or a binary request names 130 dimensions
- **THEN** each raises `unexpected_response`

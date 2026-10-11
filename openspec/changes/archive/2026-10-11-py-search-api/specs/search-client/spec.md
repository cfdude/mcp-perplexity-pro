## Purpose

Defines how the client talks to the Perplexity Search API: sending a search request, parsing its response tolerantly, the retry rules for a billed POST, how the Search API's flat error bodies map onto the server's error categories, and the diagnostics logged for each call.

## ADDED Requirements

### Requirement: Search call
The client SHALL provide one Search operation, `POST /search` with a JSON request body, returning the parsed response: the ranked `results` and the request `id`. It SHALL use the general read timeout (a search answers in well under a second) and the same bearer credential as every other call.

#### Scenario: Search succeeds
- **WHEN** the API answers a search request with the recorded fast single-query response
- **THEN** the client returns a response whose `id` and five `results` match that body, each with a title, url and snippet

#### Scenario: General timeout
- **WHEN** a search request is sent
- **THEN** it carries the general read timeout of 60 seconds, not the longer Agent run timeout

### Requirement: Tolerant search parsing
A search response SHALL be parsed with every unknown field kept, at the top level and inside each result. Only `results`, a list, is required: its items and their fields are kept as received whatever their type (a null title, a numeric date or a non-object item is not a parse failure, so a billed 200 is never lost), and `id` is optional. A response without `results`, or with `results` not a list, SHALL raise `unexpected_response` naming `/search` and `results`.

#### Scenario: Dates absent
- **WHEN** a result in the recorded response has no `date` key
- **THEN** parsing succeeds and that result is kept as received, with its `last_updated` and without a `date` key

#### Scenario: Unknown fields kept
- **WHEN** a response carries a top-level `server_time` and `usage` and a result carries an extra field
- **THEN** parsing succeeds and every one of them is retained as received

#### Scenario: Odd values kept
- **WHEN** a response holds a result whose `title` is null and whose `date` is a number, and another item that is a string
- **THEN** parsing succeeds and all of it is retained as received

#### Scenario: Empty results
- **WHEN** the API answers with the recorded response whose `results` is an empty list
- **THEN** the client returns a response with no results and the request `id`

#### Scenario: Missing results
- **WHEN** a response body is `{"id": "x"}`
- **THEN** the client raises `unexpected_response` naming `/search` and `results`

#### Scenario: Results not a list
- **WHEN** a response body is `{"id": "x", "results": {"a": 1}}`
- **THEN** the client raises `unexpected_response` naming `/search` and `results`

### Requirement: Search requests are not replayed
A search request is a billed POST. The client SHALL NOT retry it after an HTTP response other than 429, nor after a timeout once the request was sent, and SHALL retry it after a connect failure and after a 429, waiting for `Retry-After` when given, exactly as the create-request and rate-limit rules say.

#### Scenario: 5xx on search
- **WHEN** a search request returns 503
- **THEN** the client raises `upstream_failure` after exactly one request

#### Scenario: Read timeout on search
- **WHEN** a search request is sent and its read times out
- **THEN** the client raises `network_timeout` and exactly one request was sent

#### Scenario: Rate limited then served
- **WHEN** a search returns 429 with `Retry-After: 1` and then the recorded fast response
- **THEN** the client waits at least 1 second and returns the response after two requests

### Requirement: Search error mapping
Search API failures SHALL map by HTTP status to the existing categories and keep the API's message, redacted: every validation failure is HTTP 400 (the documented 422 does not occur) and is `invalid_request` whatever the error `type` (`invalid_request`, `invalid_country_code`, `invalid_language_code`); 401 is `authentication`. The error SHALL carry the API's message as `api_message`. The client SHALL NOT interpret a message.

#### Scenario: Validation message passes through
- **WHEN** the API returns the recorded 400 for a six-query request
- **THEN** the client raises `invalid_request` whose message includes `maximum 5 queries allowed, got 6`

#### Scenario: Typed validation error
- **WHEN** the API returns the recorded 400 of type `invalid_country_code`
- **THEN** the client raises `invalid_request`, and the error's `api_type` is `invalid_country_code`

#### Scenario: Bad credential
- **WHEN** the API returns the recorded 401 with type `invalid_api_key`
- **THEN** the client raises `authentication` and the message contains no credential

#### Scenario: Unparseable body
- **WHEN** the API returns the recorded 400 for a truncated JSON body
- **THEN** the client raises `invalid_request` with the API's text

#### Scenario: Echoed key
- **WHEN** a 400 body echoes a string shaped like an API key
- **THEN** the raised error contains a redaction marker in its place

### Requirement: Search call diagnostics
Each Search API call SHALL be logged like any upstream call: method, path, status, the upstream request id from the `x-request-id` header when present, attempt and elapsed time, and never the request body (the query) or the response body.

#### Scenario: Request id logged
- **WHEN** a search completes with the recorded response headers
- **THEN** one log record carries `/search`, status 200 and the `x-request-id` value, and contains none of the query text

# perplexity-client Specification

## Purpose
Defines how the server talks to the Perplexity API: authentication, error reporting, retry behavior and tolerance of response changes, so every tool built on it fails and recovers the same way.

## Requirements

### Requirement: Authenticated requests
Every request to the Perplexity API SHALL carry the configured API key as a bearer credential and be sent to a base URL that defaults to `https://api.perplexity.ai` and is overridable by configuration.

#### Scenario: Default target
- **WHEN** the client makes any request with no base URL configured
- **THEN** the request goes to `https://api.perplexity.ai` with an `Authorization: Bearer <key>` header

#### Scenario: Overridden target
- **WHEN** the base URL is configured as `http://localhost:9999`
- **THEN** requests go to that host and not to `api.perplexity.ai`

### Requirement: Typed error taxonomy
The client SHALL convert every failure into exactly one category, carrying the HTTP status, the API's error type and code when present, and an actionable message. The categories are `invalid_request` (400, 422), `authentication` (401), `forbidden` (403), `not_found` (404), `rate_limited` (429), `upstream_failure` (5xx), `network_timeout` and `unexpected_response`. These names are the stable identifiers used by every upstream-derived tool error.

#### Scenario: Retired endpoint
- **WHEN** the API returns 403 with error `type` `chat_completions_not_available` (its `code` is the integer 403)
- **THEN** the client raises a `forbidden` error that includes that `type` and the API's message

#### Scenario: Validation failure
- **WHEN** the API returns 400 with an error message
- **THEN** the client raises an `invalid_request` error whose message includes the API's message

#### Scenario: Timeout
- **WHEN** no response arrives within the configured read timeout
- **THEN** the client raises a `network_timeout` error that states which timeout elapsed

### Requirement: Network failures
`network_timeout` SHALL be raised for every failure to complete an exchange without an HTTP response: connect failure, DNS failure, connection reset and any timeout. A connect timeout counts as a connect failure for retry purposes; a write timeout uses the read timeout and a pool timeout the connect timeout. A 200 response whose body is not valid JSON is `unexpected_response`.

#### Scenario: Connection failure
- **WHEN** every attempt fails to connect to the API
- **THEN** the client raises `network_timeout` stating that the connection failed

#### Scenario: Invalid JSON body
- **WHEN** the API returns 200 with a body that is not JSON
- **THEN** the client raises `unexpected_response`

### Requirement: Unlisted statuses
A response status that no category lists, such as 3xx, 402, 405, 409 or 413, SHALL map to `unexpected_response` and carry its status and the API's message.

#### Scenario: Payload too large
- **WHEN** the API returns 413
- **THEN** the client raises `unexpected_response` carrying status 413

### Requirement: Rate-limit retry
On HTTP 429 the client SHALL wait for the `Retry-After` duration when present, otherwise use exponential backoff with jitter, then retry up to a configured maximum number of attempts (default 3). `Retry-After` is read as seconds or as an HTTP date. A value longer than the configured maximum wait (default 30 seconds) SHALL NOT be waited out; the client raises `rate_limited` at once. After the last attempt it SHALL raise `rate_limited`.

#### Scenario: Retry-After honored
- **WHEN** the first response is 429 with `Retry-After: 2` and the second is 200
- **THEN** the client waits at least 2 seconds, retries once, and returns the 200 result

#### Scenario: Attempts exhausted
- **WHEN** every attempt returns 429
- **THEN** the client raises `rate_limited` after the configured number of attempts

#### Scenario: Retry-After above the cap
- **WHEN** a 429 carries `Retry-After: 600` and the maximum wait is 30 seconds
- **THEN** the client raises `rate_limited` without sleeping

### Requirement: Create requests are not replayed
The client SHALL NOT retry a request that creates work (a POST) after the API has responded with any HTTP status other than 429; a 429 is a rejection that is never billed and follows the rate-limit retry rule. It SHALL NOT retry a create request after a timeout that occurs once the request was sent, because the run may already exist and be billed. It SHALL retry a create request after a connect failure, where the request was provably not sent, and in no other circumstance.

#### Scenario: 5xx on create
- **WHEN** a POST that creates a run returns 503
- **THEN** the client raises `upstream_failure` without sending a second request

#### Scenario: Rate limited on create
- **WHEN** a POST that creates a run returns 429 with `Retry-After: 2` and then 200
- **THEN** the client returns the 200 result after two requests

#### Scenario: Read timeout on create
- **WHEN** a POST that creates a run is sent and the read times out
- **THEN** the client raises `network_timeout` and exactly one request was sent

#### Scenario: Connect failure on create
- **WHEN** a POST fails to connect on the first attempt and connects on the second
- **THEN** the client returns the second attempt's result

### Requirement: Reads are retried
The client SHALL retry idempotent reads (GET) on 5xx, on timeouts and on connection failure, using the same backoff and attempt limit as rate-limit retry.

#### Scenario: 5xx on read
- **WHEN** a GET returns 503 and then 200
- **THEN** the client returns the 200 result

### Requirement: Tolerant response parsing
The client SHALL accept responses that contain fields it does not know about and SHALL keep them available to callers. A missing optional field SHALL NOT cause a failure. A missing field a caller depends on SHALL raise `unexpected_response` naming the endpoint and field.

#### Scenario: Unknown field
- **WHEN** a response contains a field the client has no definition for
- **THEN** parsing succeeds and the field is retained on the parsed result

#### Scenario: Missing required field
- **WHEN** a `GET /v1/models` response lacks `data`
- **THEN** the client raises `unexpected_response` naming `/v1/models` and `data`

### Requirement: Upstream text is redacted
Before an upstream error message is stored, logged or returned, the client SHALL remove the configured API key and any token shaped like an API key from it.

#### Scenario: Upstream echoes a key
- **WHEN** an error body contains a string shaped like an API key
- **THEN** the raised error and the log record contain a redaction marker in its place

### Requirement: Request diagnostics without prompt content
For each upstream call the client SHALL log method, path, status, upstream request id when present, attempt number and elapsed time. It SHALL NOT log prompt text, response bodies or credentials at the default log level.

#### Scenario: Successful call
- **WHEN** a call completes
- **THEN** one log record contains method, path, status, request id and elapsed time, and contains none of the request body

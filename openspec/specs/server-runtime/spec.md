# server-runtime Specification

## Purpose
Defines how the MCP server starts, serves clients over stdio and HTTP, reports health, loads configuration, and shuts down, so that it can be run and supervised the same way every time.

## Requirements

### Requirement: Transports
The server SHALL serve MCP over stdio and over Streamable HTTP. The HTTP endpoint SHALL be `/mcp` on host `127.0.0.1` and port 8102 by default, with host and port overridable by configuration. One documented command SHALL start each transport. The HTTP endpoints carry no authentication, so the default host SHALL NOT be a non-loopback address.

#### Scenario: HTTP default endpoint
- **WHEN** the server is started in HTTP mode with no port configured
- **THEN** an MCP `initialize` request to `http://127.0.0.1:8102/mcp` succeeds and lists the registered tools

#### Scenario: Default host
- **WHEN** the server is started in HTTP mode with no host configured
- **THEN** it accepts connections on the loopback interface and refuses connections addressed to the machine's LAN address (verification is skipped on a host with no non-loopback address)

#### Scenario: Port override
- **WHEN** the port is set to 8199 by configuration
- **THEN** the server listens on 8199 and does not listen on 8102

#### Scenario: stdio mode
- **WHEN** the server is started in stdio mode
- **THEN** it completes an MCP `initialize` exchange over stdin and stdout and opens no network listener

### Requirement: Non-loopback host warning
The server SHALL log a warning at startup when the configured host is not a loopback address, because its endpoints are unauthenticated. Use beyond loopback is unsupported until authentication exists.

#### Scenario: Host set to all interfaces
- **WHEN** the server starts in HTTP mode with the host set to `0.0.0.0`
- **THEN** a warning stating that the endpoints are unauthenticated is logged to stderr

#### Scenario: Loopback host
- **WHEN** the server starts with host `127.0.0.1`, `::1` or `localhost`
- **THEN** no such warning is logged

### Requirement: Startup order and failure
At startup the server SHALL validate settings first, then create the data directory and apply database migrations, then build the upstream client, and only then accept connections. A failure at any step SHALL abort startup before any listener opens. A settings failure SHALL NOT create or modify anything on disk. A database failure aborts the whole server, including `/health` and tools that do not use the database.

#### Scenario: Settings failure touches nothing
- **WHEN** startup fails because `PERPLEXITY_API_KEY` is missing and the data directory does not exist
- **THEN** the data directory is not created

#### Scenario: Migration failure
- **WHEN** a migration fails at startup
- **THEN** the process exits non-zero before any listener opens and `/health` is not served

### Requirement: Tool error contract
Every tool failure SHALL be returned as an MCP tool error whose structured content carries a stable `category` and a sanitized `message`. An unexpected exception SHALL carry category `internal_error` and a generic message, never its text.

#### Scenario: Upstream failure in a tool
- **WHEN** a tool call fails because the API returned 401
- **THEN** the tool error has category `authentication` and a message that contains no credential

#### Scenario: Unexpected exception
- **WHEN** a tool raises an exception the server did not anticipate
- **THEN** the client receives category `internal_error` with a generic message without the exception text, and the full detail is logged to stderr with secrets redacted

#### Scenario: Invalid arguments
- **WHEN** a client calls a tool with a missing or mistyped argument
- **THEN** the tool error has category `invalid_request` and names the argument

### Requirement: Error category vocabulary
The `category` of a tool error SHALL be one of: `invalid_request`, `authentication`, `forbidden`, `not_found`, `rate_limited`, `upstream_failure`, `network_timeout`, `unexpected_response`, `confirmation_required`, `storage_busy` or `internal_error`.

#### Scenario: Closed vocabulary
- **WHEN** any tool fails for any reason
- **THEN** its `category` is exactly one of the eleven listed values

### Requirement: Protocol output is never polluted
In stdio mode the server SHALL write only MCP protocol messages to stdout. All logs and diagnostics SHALL go to stderr.

#### Scenario: Logging in stdio mode
- **WHEN** a tool call logs at any level while the server runs in stdio mode
- **THEN** stdout contains only valid MCP messages and the log line appears on stderr

### Requirement: Health endpoint
In HTTP mode the server SHALL expose `GET /health` that requires no authentication, makes no upstream call, and returns HTTP 200 with JSON containing `status` and `version`.

#### Scenario: Healthy server
- **WHEN** a client sends `GET /health`
- **THEN** the response is 200 with `{"status": "ok", "version": "<server version>"}` and no request is made to the Perplexity API

### Requirement: Single version source
The version reported in `/health`, in the MCP `initialize` result, and in package metadata SHALL be the same value.

#### Scenario: Versions agree
- **WHEN** the three version values are read
- **THEN** they are identical

### Requirement: Configuration from environment
The server SHALL read configuration from environment variables with the prefix `PERPLEXITY_` and validate it at startup. `PERPLEXITY_API_KEY` is required. These are optional with documented defaults: `HOST`, `PORT`, `BASE_URL`, `DATA_DIR`, `LOG_LEVEL`, `CONNECT_TIMEOUT`, `READ_TIMEOUT`, `AGENT_READ_TIMEOUT`, `MAX_ATTEMPTS`, `MAX_RETRY_WAIT`, `CATALOG_TTL`, `CATALOG_MAX_STALE`, `DB_BUSY_TIMEOUT`, `ROUTING` and `MODEL`; `TIER_LIGHT`, `TIER_STANDARD` and `TIER_COMPLEX` are required exactly when `ROUTING` is `custom` (see `routing-config`). Invalid values SHALL abort startup with a message naming the variable.

#### Scenario: Documented defaults
- **WHEN** only `PERPLEXITY_API_KEY` is set
- **THEN** the settings are host `127.0.0.1`, port 8102, base URL `https://api.perplexity.ai`, data directory `~/.perplexity-pro/`, log level INFO, connect timeout 10 s, read timeout 60 s, agent read timeout 120 s, 3 attempts, 30 s maximum retry wait, catalog TTL 3600 s, maximum stale age 86400 s, database busy timeout 5 s, routing `standard` and model `perplexity/sonar`

#### Scenario: Missing API key
- **WHEN** the server starts without `PERPLEXITY_API_KEY`
- **THEN** startup fails with a message naming `PERPLEXITY_API_KEY` and the process exits non-zero before accepting any connection

#### Scenario: Invalid port
- **WHEN** the port variable is set to a non-integer
- **THEN** startup fails with a message naming that variable and the offending value

#### Scenario: Agent read timeout override
- **WHEN** `PERPLEXITY_AGENT_READ_TIMEOUT` is set to 240, and separately to `0` or `soon`
- **THEN** the first starts with an agent read timeout of 240 s, and each of the others fails startup with a message naming `PERPLEXITY_AGENT_READ_TIMEOUT` and the offending value

#### Scenario: Several routing errors at once
- **WHEN** `PERPLEXITY_ROUTING` is `custom` with two tier variables missing
- **THEN** one startup message names both missing variables

### Requirement: Secrets are never emitted
The configured API key SHALL NOT appear in logs, error messages, tool results, `/health` or any file the server writes, and no string shaped like an API key (`pplx-` followed by key characters) SHALL appear in text the server itself originates. Content supplied by the caller, generated by the model or returned by a web search (query, instructions, messages, answers, titles, snippets, URLs, dates) may contain key-shaped examples and is stored and returned as given.

#### Scenario: Upstream authentication failure
- **WHEN** the Perplexity API rejects the key and the failure is logged and returned to the client
- **THEN** neither the log nor the returned error contains the key or any `pplx-`-shaped token

#### Scenario: Key-shaped example in content
- **WHEN** a query, the model's answer, or a search result's snippet contains a `pplx-` shaped example that is not the configured key
- **THEN** the example is stored and returned as given, and no log record, error message or `/health` response contains it

#### Scenario: Configured key in content
- **WHEN** a query, message, title, answer, source, or search snippet, title, url, date or last-updated value contains the configured key itself
- **THEN** the key is replaced by `[redacted]` before it is stored or returned, any key-shaped example beside it is left as given, and no result, log record or stored row contains the key

### Requirement: Graceful shutdown
On SIGINT or SIGTERM, or on stdin reaching end of file in stdio mode, the server SHALL stop accepting new requests, let in-flight requests finish for at most 10 seconds, close its upstream HTTP client and database connections, and exit 0. The supervisor's kill timeout SHALL be longer than that bound.

#### Scenario: SIGTERM during idle
- **WHEN** the process receives SIGTERM with no requests in flight
- **THEN** it logs that the upstream client and database engine were closed and exits with status 0 within 5 seconds

#### Scenario: SIGINT during idle
- **WHEN** the process receives SIGINT with no requests in flight
- **THEN** it behaves as for SIGTERM

#### Scenario: New call while draining
- **WHEN** a stdio-mode server is draining after a signal and a new tool call arrives
- **THEN** the call fails with category `internal_error` and a message containing `shutting down`

#### Scenario: stdin closed in stdio mode
- **WHEN** the client closes stdin of a stdio-mode server
- **THEN** it closes its resources and exits with status 0

#### Scenario: In-flight request that outlives the bound
- **WHEN** SIGTERM arrives while a tool call is still running and it has not finished after 10 seconds
- **THEN** the server closes its resources and exits without waiting further

#### Scenario: In-flight request at SIGTERM
- **WHEN** SIGTERM arrives while a tool call is still running and it finishes within 10 seconds
- **THEN** the client receives that call's result before the process exits

### Requirement: Supervised operation
The server SHALL run under pm2 using one documented start command, with a kill timeout of at least 15 seconds, and SHALL resume serving on the same port after `pm2 restart`.

#### Scenario: Configured kill timeout
- **WHEN** the pm2 configuration for the server is read
- **THEN** its kill timeout is at least 15 seconds

#### Scenario: Restart under pm2
- **WHEN** `pm2 restart` is issued for the server
- **THEN** `GET /health` returns 200 on the configured port once startup completes

### Requirement: Server instructions
The server SHALL set the MCP `instructions` of its `initialize` result from the active configuration (the content is owned by `routing-config` "The instructions text"), and the text SHALL be a pure function of the settings (same settings, same text, no secrets, no clock).

#### Scenario: Instructions present
- **WHEN** a client calls `initialize`
- **THEN** the result carries non-empty instructions naming the routing mode

#### Scenario: Stable text
- **WHEN** two servers start with the same settings
- **THEN** their instructions are byte-identical

### Requirement: Invalid requests point to help
A tool failure with category `invalid_request` raised by a tool that has a help entry, other than `perplexity_help` itself, SHALL end its message with one sentence naming the help call for that tool: `Call perplexity_help with action "tool" and name "<tool>" for its arguments and examples.` The category, the structured `category` and every other part of the message SHALL be unchanged, and no other category SHALL gain the sentence.

#### Scenario: A bad argument
- **WHEN** a client calls `perplexity_ask` with a depth `turbo`
- **THEN** the error is `invalid_request`, its message states the depth problem and ends with the sentence naming `perplexity_help` and `perplexity_ask`

#### Scenario: Argument validation by the framework
- **WHEN** a client passes a value of the wrong type to a tool
- **THEN** the same sentence is appended to that `invalid_request`

#### Scenario: Other categories are untouched
- **WHEN** an upstream call fails with `rate_limited`
- **THEN** the message has no help sentence

#### Scenario: Help's own errors
- **WHEN** a client asks `perplexity_help` for an unknown tool, or passes it an action it does not have
- **THEN** the message lists the valid names (or the framework's complaint) and has no extra help sentence

#### Scenario: A tool without a help entry
- **WHEN** a tool that has no help entry fails with `invalid_request`
- **THEN** its message has no help sentence, because the call it would name does not exist

### Requirement: Dynamic mode configuration
In `dynamic` mode `PERPLEXITY_MODEL`, `PERPLEXITY_TIER_LIGHT`, `PERPLEXITY_TIER_STANDARD` and `PERPLEXITY_TIER_COMPLEX` SHALL all be optional: the tier variables replace a tier's default, and a startup with none of them set SHALL succeed. The configuration rules of "Routing mode" and the model-id rules of `routing-config` apply to each variable that is set and used.

#### Scenario: Nothing set
- **WHEN** the server starts with `PERPLEXITY_ROUTING=dynamic` and only the API key
- **THEN** startup succeeds with the default tiers

### Requirement: The classifier variable
`PERPLEXITY_CLASSIFIER` SHALL be an optional configuration variable (default `rules`) read with the other `PERPLEXITY_` variables and validated at startup as `routing-config` "The classifier setting" says.

#### Scenario: Default
- **WHEN** the server starts with only the API key
- **THEN** the classifier setting is `rules`

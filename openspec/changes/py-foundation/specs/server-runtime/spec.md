# Spec Delta

## Purpose

Defines how the MCP server starts, serves clients over stdio and HTTP, reports health, loads configuration, and shuts down, so that it can be run and supervised the same way every time.

## ADDED Requirements

### Requirement: Transports
The server SHALL serve MCP over stdio and over Streamable HTTP. The HTTP endpoint SHALL be `/mcp` on host `127.0.0.1` and port 8102 by default, with host and port overridable by configuration. One documented command SHALL start each transport. The HTTP endpoints carry no authentication, so the default host SHALL NOT be a non-loopback address.

#### Scenario: HTTP default endpoint
- **WHEN** the server is started in HTTP mode with no port configured
- **THEN** an MCP `initialize` request to `http://127.0.0.1:8102/mcp` succeeds and lists the registered tools

#### Scenario: Default host
- **WHEN** the server is started in HTTP mode with no host configured
- **THEN** it accepts connections on the loopback interface and refuses connections addressed to the machine's LAN address

#### Scenario: Port override
- **WHEN** the port is set to 8199 by configuration
- **THEN** the server listens on 8199 and does not listen on 8102

#### Scenario: stdio mode
- **WHEN** the server is started in stdio mode
- **THEN** it completes an MCP `initialize` exchange over stdin and stdout and opens no network listener

### Requirement: Startup order and failure
At startup the server SHALL validate settings first, then create the data directory and apply database migrations, then build the upstream client, and only then accept connections. A failure at any step SHALL abort startup before any listener opens. A settings failure SHALL NOT create or modify anything on disk. A database failure aborts the whole server, including `/health` and tools that do not use the database.

#### Scenario: Settings failure touches nothing
- **WHEN** startup fails because `PERPLEXITY_API_KEY` is missing and the data directory does not exist
- **THEN** the data directory is not created

#### Scenario: Migration failure
- **WHEN** a migration fails at startup
- **THEN** the process exits non-zero before any listener opens and `/health` is not served

### Requirement: Tool error contract
Every tool failure SHALL be returned as an MCP tool error whose structured content carries a stable `category` and a sanitized `message`. The categories are the eight client categories (`invalid_request`, `authentication`, `forbidden`, `not_found`, `rate_limited`, `upstream_failure`, `network_timeout`, `unexpected_response`) plus `confirmation_required` and `storage_busy`. Text of unexpected exceptions SHALL NOT reach the client.

#### Scenario: Upstream failure in a tool
- **WHEN** a tool call fails because the API returned 401
- **THEN** the tool error has category `authentication` and a message that contains no credential

#### Scenario: Unexpected exception
- **WHEN** a tool raises an exception the server did not anticipate
- **THEN** the client receives a generic error message without the exception text and the full detail is logged to stderr with secrets redacted

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
The server SHALL read configuration from environment variables with the prefix `PERPLEXITY_` and validate it at startup. `PERPLEXITY_API_KEY` is required. These are optional with documented defaults: `HOST`, `PORT`, `BASE_URL`, `DATA_DIR`, `LOG_LEVEL`, `CONNECT_TIMEOUT`, `READ_TIMEOUT`, `MAX_ATTEMPTS`, `MAX_RETRY_WAIT`, `CATALOG_TTL`, `CATALOG_MAX_STALE` and `DB_BUSY_TIMEOUT`. Invalid values SHALL abort startup with a message naming the variable.

#### Scenario: Missing API key
- **WHEN** the server starts without `PERPLEXITY_API_KEY`
- **THEN** startup fails with a message naming `PERPLEXITY_API_KEY` and the process exits non-zero before accepting any connection

#### Scenario: Invalid port
- **WHEN** the port variable is set to a non-integer
- **THEN** startup fails with a message naming that variable and the offending value

### Requirement: Secrets are never emitted
The API key SHALL NOT appear in logs, error messages, tool results, `/health`, or any file the server writes, including partial forms such as a prefix.

#### Scenario: Upstream authentication failure
- **WHEN** the Perplexity API rejects the key and the failure is logged and returned to the client
- **THEN** neither the log nor the returned error contains any part of the key

### Requirement: Graceful shutdown
On SIGINT or SIGTERM the server SHALL stop accepting new requests, let in-flight requests finish for at most 10 seconds, close its upstream HTTP client and database connections, and exit 0. The supervisor's kill timeout SHALL be longer than that bound.

#### Scenario: SIGTERM during idle
- **WHEN** the process receives SIGTERM with no requests in flight
- **THEN** it logs that the upstream client and database engine were closed and exits with status 0 within 5 seconds

#### Scenario: SIGINT during idle
- **WHEN** the process receives SIGINT with no requests in flight
- **THEN** it behaves as for SIGTERM

#### Scenario: In-flight request at SIGTERM
- **WHEN** SIGTERM arrives while a tool call is still running and it finishes within 10 seconds
- **THEN** the client receives that call's result before the process exits

### Requirement: Supervised operation
The server SHALL run under pm2 using one documented start command and SHALL resume serving on the same port after `pm2 restart`.

#### Scenario: Restart under pm2
- **WHEN** `pm2 restart` is issued for the server
- **THEN** `GET /health` returns 200 on the configured port once startup completes

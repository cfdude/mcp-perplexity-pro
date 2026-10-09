# MCP Perplexity Pro

An [MCP](https://modelcontextprotocol.io) server for the Perplexity API, written in Python
(FastMCP, SQLAlchemy, SQLite). It serves MCP over stdio or Streamable HTTP and keeps its own data
in a local SQLite database.

## Status: 2.0.0 is a foundation release

Version 2.0.0 replaces the TypeScript 1.x server. The reason is that Perplexity retired the Sonar
endpoints the 1.x server called: both `POST /chat/completions` and `GET /async/chat/completions`
now return `403 chat_completions_not_available` ("Sonar is now the Agent API"), so 1.x could not
answer a single query. There was no working behavior to port, so the TypeScript code is deleted
(git history keeps it) and the server was rebuilt in Python.

**Only two tools exist today:**

| Tool | What it does |
|---|---|
| `perplexity_models` | Lists the models your key can use, with live prices, plus the documented Agent API presets |
| `perplexity_projects` | Lists projects, or deletes one with everything stored in it |

The Agent, Search, Embeddings and Decisions tools arrive in later releases. The old tool names
(`ask_perplexity`, `chat_perplexity` and the rest) are gone and are not coming back under those
names. No data is imported from 1.x.

## Install and run

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this repository> && cd mcp-perplexity-pro
uv sync
export PERPLEXITY_API_KEY=<your-perplexity-api-key>
```

Start commands:

```bash
# stdio (the default transport): the MCP client launches this process
uv run mcp-perplexity-pro --transport stdio

# Streamable HTTP on http://127.0.0.1:8102/mcp (health: http://127.0.0.1:8102/health)
uv run mcp-perplexity-pro --transport http

# without a checkout-managed environment
uvx --from . mcp-perplexity-pro --transport http

# check the install
uv run mcp-perplexity-pro --version
uv run mcp-perplexity-pro --help
```

In stdio mode stdout carries only MCP messages; every log line goes to stderr. A missing or invalid
setting prints a message naming the variable and exits with status 1 before anything is created
on disk or any port is opened.

### Run under pm2

The supervised setup is one pm2 app that runs the HTTP transport on port 8102. Copy the example
configuration, set your key in the copy, and start it. The copy is gitignored so the key never
enters the repository:

```bash
cp ecosystem.example.cjs ecosystem.config.cjs   # then replace REPLACE_ME with your key
pm2 start ecosystem.config.cjs
curl -s http://127.0.0.1:8102/health            # {"status":"ok","version":"2.0.0"}
```

`kill_timeout` is 15000 ms because on SIGTERM or SIGINT the server finishes in-flight calls for up
to 10 seconds, closes its HTTP client and database connections, and exits 0; pm2 must wait longer
than that before it sends SIGKILL. `pm2 restart mcp-perplexity-pro` brings the server back on the
same port.

## Settings

All settings are environment variables with the prefix `PERPLEXITY_`. They are validated at
startup; an invalid value aborts startup with a message naming the variable and the offending
value. No `.env` file is read.

| Variable | Default | Meaning |
|---|---|---|
| `PERPLEXITY_API_KEY` | none, required | The Perplexity API key. Never logged, returned or stored on disk |
| `PERPLEXITY_HOST` | `127.0.0.1` | HTTP bind host. A non-loopback value logs a startup warning (see Security) |
| `PERPLEXITY_PORT` | `8102` | HTTP port, 1 to 65535 |
| `PERPLEXITY_BASE_URL` | `https://api.perplexity.ai` | Perplexity API base URL (`http` or `https`) |
| `PERPLEXITY_DATA_DIR` | `~/.perplexity-pro/` | Where the SQLite database, migration lock and backups live |
| `PERPLEXITY_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` (case-insensitive) |
| `PERPLEXITY_CONNECT_TIMEOUT` | `10` | Seconds to establish a connection to the API |
| `PERPLEXITY_READ_TIMEOUT` | `60` | Seconds to wait for the API's response |
| `PERPLEXITY_MAX_ATTEMPTS` | `3` | Attempts per API request (retries apply to HTTP 429, honoring `Retry-After`, and to safe reads) |
| `PERPLEXITY_MAX_RETRY_WAIT` | `30` | Longest wait in seconds between attempts; a `Retry-After` longer than this is not waited out |
| `PERPLEXITY_CATALOG_TTL` | `3600` | Seconds the model list is cached |
| `PERPLEXITY_CATALOG_MAX_STALE` | `86400` | Oldest cached model list, in seconds, that may be returned when the live request fails |
| `PERPLEXITY_DB_BUSY_TIMEOUT` | `5` | Seconds a write waits for the database lock before failing with `storage_busy` |

Variables starting with `FASTMCP_` belong to FastMCP and are not used for this server's own
settings.

## Client configuration

### Claude Code over HTTP (`.mcp.json`)

Start the server first (pm2 or `uv run mcp-perplexity-pro --transport http`), then:

```json
{
  "mcpServers": {
    "perplexity": {
      "type": "http",
      "url": "http://localhost:8102/mcp"
    }
  }
}
```

The URL is the same as in 1.x. The equivalent command is
`claude mcp add --transport http perplexity http://localhost:8102/mcp`.

### Over stdio

The client launches the server, so the key goes in the client's `env` block:

```json
{
  "mcpServers": {
    "perplexity": {
      "command": "uv",
      "args": [
        "run", "--directory", "/absolute/path/to/mcp-perplexity-pro",
        "mcp-perplexity-pro", "--transport", "stdio"
      ],
      "env": { "PERPLEXITY_API_KEY": "<your-perplexity-api-key>" }
    }
  }
}
```

## Tools

### `perplexity_models`

Lists the models available to the configured key, from the live `GET /v1/models`, with prices as
the API reports them. Nothing is hardcoded, so the list and prices track Perplexity.

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `provider` | string | all | Only models from this provider, compared case-insensitively (for example `anthropic`) |
| `refresh` | boolean | `false` | Bypass the cache and fetch the list now |

Output (`structuredContent`, with the same data rendered as text):

| Key | Meaning |
|---|---|
| `models` | Entries with `id`, `provider` (the API's `owned_by`) and `pricing`: `input`, `output`, `cache_read`, `cache_write`, `unit`. A field the API did not supply is `null` |
| `providers` | Every provider in the live list, ignoring the filter, so a typo in `provider` shows the real names |
| `stale` | `true` when the live request failed and an older cached list is shown instead |
| `age_seconds` | Seconds since the list was fetched live |
| `presets` | The Agent API preset names (`fast`, `low`, `medium`, `high`, `xhigh`) and the model each maps to, with `source: "documentation"` and `as_of` (the recording date). Presets are copied from Perplexity's documentation, not live data, and the model behind a name can change |

A failed refresh serves the cached list (`stale: true`) only for `rate_limited`, `upstream_failure`
and `network_timeout`, and only while it is younger than `PERPLEXITY_CATALOG_MAX_STALE`. An
`authentication` or `forbidden` failure is always returned as an error, never hidden behind a cache.

Example call and result (values are from the recorded fixture `tests/fixtures/models.json`,
captured 2026-10-09; the real list changes):

```json
{"name": "perplexity_models", "arguments": {"provider": "anthropic"}}
```

```json
{
  "models": [
    {
      "id": "anthropic/claude-haiku-4-5",
      "provider": "anthropic",
      "pricing": {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write": 1.25,
                  "unit": "usd_per_1m_tokens"}
    }
  ],
  "providers": ["anthropic", "google", "openai", "perplexity", "xai"],
  "stale": false,
  "age_seconds": 0.0,
  "presets": {
    "source": "documentation",
    "as_of": "2026-10-06",
    "presets": [
      {"name": "fast", "model": "openai/gpt-6-luna"},
      {"name": "xhigh", "model": "anthropic/claude-opus-5-5"}
    ],
    "note": "Taken from Perplexity's documentation, not from the live API. ..."
  }
}
```

The example is shortened: a real result lists every matching model (14 for `anthropic` in that
fixture) and all five presets.

### `perplexity_projects`

Projects group everything the server stores. Later tools create a project the first time they
name one and use the project `default` when none is given; this tool only looks projects up and
never creates one. Project names are case-sensitive, 1 to 64 characters of ASCII letters, digits,
`-`, `_` and `.`, may not begin with `.`, and may not look like an API key.

| Argument | Type | Meaning |
|---|---|---|
| `action` | `list` or `delete` | Required. `list` shows all projects; `delete` removes one |
| `project` | string | Project name (`delete` only) |
| `confirm` | boolean | Must be `true` for `delete`; deletion cannot be undone |

Output: `action`; for `list`, `projects` (each with `name` and `created_at`, UTC); for `delete`,
`project` and `rows_removed` (rows removed from tables that reference the project directly; rows
two levels down go by cascade and are not counted). The project `default` may be deleted; it is
recreated on next use. Because no 2.0.0 tool stores records yet, a fresh install lists no projects.

```json
{"name": "perplexity_projects", "arguments": {"action": "list"}}
```

```json
{"action": "list", "projects": [{"name": "demo", "created_at": "2026-10-09T17:36:14Z"}],
 "project": null, "rows_removed": null}
```

```json
{"name": "perplexity_projects", "arguments": {"action": "delete", "project": "demo", "confirm": true}}
```

```json
{"action": "delete", "projects": null, "project": "demo", "rows_removed": 0}
```

## Errors

Every tool failure is an MCP tool error (`isError: true`) in exactly one of eleven categories. A
client can read the category three ways:

- `structuredContent.category` (with `structuredContent.message`), for code
- `_meta.category`, for code that only looks at metadata
- the text content, which always starts `[category] message`, for clients that show only text

```json
{"isError": true,
 "structuredContent": {"category": "confirmation_required",
   "message": "Deleting project 'demo' removes all its data and cannot be undone; call again with confirm=true."},
 "_meta": {"category": "confirmation_required"},
 "content": [{"type": "text", "text": "[confirmation_required] Deleting project 'demo' removes ..."}]}
```

| Category | Meaning |
|---|---|
| `invalid_request` | A missing or mistyped argument, an invalid project name, or HTTP 400/422 from the API |
| `authentication` | The API rejected the key (HTTP 401) |
| `forbidden` | The key is not allowed to do this (HTTP 403) |
| `not_found` | Unknown tool, a project that does not exist, or HTTP 404 from the API |
| `rate_limited` | HTTP 429 after the allowed attempts |
| `upstream_failure` | HTTP 5xx from the API |
| `network_timeout` | The API did not connect or answer within the timeouts |
| `unexpected_response` | Any other HTTP status, or a response missing a field the server needs |
| `confirmation_required` | A destructive action was called without `confirm: true`; nothing changed |
| `storage_busy` | A database write waited longer than `PERPLEXITY_DB_BUSY_TIMEOUT`; retry shortly |
| `internal_error` | An unexpected failure, or a call made while the server is shutting down. The message is generic and never contains exception text; the detail is logged to stderr with secrets removed |

## Security

- **Unauthenticated, loopback by default.** The HTTP endpoints (`/mcp`, `/health`) have no
  authentication. The default host is `127.0.0.1`. If `PERPLEXITY_HOST` is anything other than
  `127.0.0.1`, `::1` or `localhost`, startup logs a warning to stderr. Use beyond loopback is
  unsupported until authentication exists.
- **Host and origin protection.** FastMCP's host and origin checks are enabled explicitly. A
  request with a foreign `Host` header gets HTTP 421 and one with a foreign `Origin` gets 403,
  which blocks DNS-rebinding attacks from a web page against the local server.
- **The key is never emitted.** It is held as a secret value and is removed, together with any
  `pplx-` shaped token, from logs, error messages, tool results, `/health` and every file the
  server writes. It is not stored in the data directory.
- **Owner-only data.** The data directory is created with mode 0700 and the database with 0600;
  a looser existing directory is tightened or startup fails naming it.
- The server never writes into the working directory of the project that calls it.

## Data and backups

Everything persistent lives in `PERPLEXITY_DATA_DIR` (default `~/.perplexity-pro/`):

| File | Purpose |
|---|---|
| `perplexity.db` | The SQLite database (WAL mode, so `perplexity.db-wal` and `perplexity.db-shm` appear while it is open) |
| `migrate.lock` | Lock file so two processes starting together cannot migrate at once |
| `backup-<rev>.db` | Copy of the database as it was at schema revision `<rev>`, taken automatically before a migration touches a database that already has a revision (for example `backup-0001.db`) |

Migrations run at startup. A failed migration rolls back and the server exits non-zero without
listening. A database that is newer than the code is refused with both versions named. The backup
exists for a migration that succeeded but turned out wrong. Restoring is manual:

1. Stop the server (`pm2 stop mcp-perplexity-pro`, or stop the stdio client).
2. Delete the write-ahead files so stale pages are not replayed over the restored file:
   `rm -f ~/.perplexity-pro/perplexity.db-wal ~/.perplexity-pro/perplexity.db-shm`
3. Copy the backup over the database:
   `cp ~/.perplexity-pro/backup-<rev>.db ~/.perplexity-pro/perplexity.db`
4. Run the previous version of the server (the one that matches that schema revision) and check
   `GET /health`.

Use your own `PERPLEXITY_DATA_DIR` in the paths if you set one. Both server processes (a pm2 HTTP
instance and a stdio instance) may share one data directory.

## Development

```bash
uv sync                              # install runtime and dev dependencies from uv.lock
uv run pytest                        # offline test suite (about 25 s)
uv run ruff check .                  # lint (ruff is the only linter)
uv run ruff format --check .         # formatting (ruff is the only formatter)
uv run pre-commit install            # once per clone: runs ruff and pytest on every commit
uv run pre-commit run --all-files    # run the commit checks by hand
```

The commit hook runs `ruff check --fix`, `ruff format` and `uv run --locked pytest`. CI
(`.github/workflows/ci.yml`) runs `uv sync --locked`, `ruff check`, `ruff format --check` and
`pytest` on Python 3.12 and 3.14 for every push and pull request. `--locked` makes the install
fail when `uv.lock` is out of date; `--frozen` would not.

### Tests

- Tests are offline. A socket guard in `tests/conftest.py` fails any connection to a non-loopback
  address; a test that truly needs the network opts out with `@pytest.mark.allow_network`.
- Upstream calls are faked by injecting an `httpx2.AsyncClient` on an `httpx2.MockTransport`
  (`respx` and `pytest-httpx` do not intercept `httpx2`).
- Recorded API responses live in `tests/fixtures/`, each with a `.meta.json` sidecar naming the
  endpoint and capture date. Fixtures come from real calls and are scanned for key-shaped strings.
- Tests marked `live` call the real API and are deselected by default (`addopts = -m 'not live'`).
  Run them deliberately with a real key:

  ```bash
  PERPLEXITY_API_KEY=<your-perplexity-api-key> uv run pytest -m live
  ```

- The fixtures capture helper is `tests/test_live_capture.py` (a `live` test). It re-records the
  fixtures, scrubs account identifiers, scans every payload for keys before writing anything, and
  stops without writing if one is found:

  ```bash
  PERPLEXITY_API_KEY=<your-perplexity-api-key> uv run pytest -m live tests/test_live_capture.py
  ```

### Layout

```
src/mcp_perplexity_pro/
  __main__.py     entry point: startup order, stdio and HTTP runners, graceful shutdown
  cli.py          argument parsing (--transport, --version)
  settings.py     PERPLEXITY_* settings and their validation
  server.py       build_server(): FastMCP wiring, AppContext, /health, error middleware
  client.py       the one Perplexity HTTP client (httpx2): retry, typed errors, redaction
  errors.py       PerplexityError and the eleven error categories
  catalog.py      model list cache, stale-on-failure rule, documented presets
  models/         tolerant pydantic models for API payloads
  tools/          one module per tool, each with register(server)
  storage/        engine, unit_of_work session, migration runner, project rules
  migrations/     Alembic environment and versions/NNNN_slug.py (packaged in the wheel)
  log_setup.py, redaction.py   stderr logging with secrets removed
tests/            offline tests, fixtures/, and the live-marked capture helper
openspec/         the spec-driven change records (py-foundation)
```

Contributor and agent guidance is in `CLAUDE.md`.

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

**Only three tools exist today:**

| Tool | What it does |
|---|---|
| `perplexity_models` | Lists the models your key can use, with live prices, plus the documented Agent API presets |
| `perplexity_projects` | Lists projects, or deletes one and its stored records (spend history is kept) |
| `perplexity_usage` | Reports what recorded upstream calls cost, grouped by tool, API, model, project or day. Read-only |

**No tool records usage yet.** The usage table and the recorder exist, but none of the three tools
above makes a costed upstream call, so `perplexity_usage` reports zero calls on a fresh install.
Real recording arrives with each later tool: Agent, Search, Embeddings and Decisions.

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
| `PERPLEXITY_MAX_ATTEMPTS` | `3` | Attempts per API request (HTTP 429 is retried honoring `Retry-After`; GET requests are also retried on 5xx, timeouts and connection failures; a create POST is retried only after a connect failure) |
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

### `perplexity_usage`

Reports what the recorded upstream Perplexity calls cost. It reads the usage events (one row per
costed upstream call, stored by the server itself) and never writes. **Nothing is recorded yet:**
no 2.0.0 tool makes a costed call, so the totals are zero until the Agent, Search, Embeddings and
Decisions tools arrive and each starts recording its own calls.

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `project` | string | all projects | Only calls recorded under this project name. Matched by the name stored with each call, so a deleted project still reports; naming one that never existed returns zeros and creates nothing |
| `since` | string | no start | First UTC day to include, written `YYYY-MM-DD` |
| `until` | string | no end | Last UTC day to include, written `YYYY-MM-DD`; the whole day is included. `9999-12-31` is refused |
| `group_by` | `tool`, `api`, `model`, `project` or `day` | `tool` | The one grouping to return |
| `limit` | integer | `20` | Most groups to return, 1 to 200 |

A bad date, `since` after `until`, a `limit` outside 1 to 200 or an invalid project name is
`invalid_request`.

Output (`structuredContent`, with a small plain-text table rendering the same data):

| Key | Meaning |
|---|---|
| `totals` | The measures over every matching call, whatever `limit` is |
| `groups` | At most `limit` entries, each the same measures plus `key`. Ordered by cost, highest first (ties by key); `day` returns the latest `limit` days in ascending order. A call with no value for the grouping column is grouped under `(none)` |
| `groups_total` | How many groups matched in all |
| `groups_truncated` | `true` when `limit` cut the list, so `groups` does not cover everything (`totals` still does) |
| `group_by`, `project`, `since`, `until`, `limit` | The filters and grouping that were applied |

The measures in `totals` and in each group: `calls`, `errors` (calls whose status is not `ok`),
`input_tokens`, `output_tokens`, `total_tokens`, `cost_nano_usd`, `cost_usd`, `calls_cost_computed`
and `calls_cost_unknown`. Money is exact. `cost_nano_usd` is an integer count of nano-USD (10^-9
USD), summed in the database, and `cost_usd` is the same amount as an exact decimal string such as
`"0.00875"` (trailing zeros trimmed, `"0"` for none), never a float.

How each call's cost is known (`cost_source`, stored per call):

- `reported`: the API returned the cost in its response, and the server stores it as given.
- `computed`: the response carried no cost, so the server priced the call from Perplexity's
  documented prices, kept in `pricing.py` and dated (`PRICES_AS_OF`). The date is stored with the
  call, so a later price change does not rewrite old rows. `calls_cost_computed` counts these.
- `none`: the cost is unknown, not free. Such a call adds 0 to the cost, and
  `calls_cost_unknown` counts it. An unknown token count likewise adds 0 to the token sums.

**The cost is a lower bound.** Error calls count cost 0 and may still have been billed, and every
unknown-cost call adds 0, so the true spend is at least the reported figure. Read
`calls_cost_unknown` next to `cost_usd`: any value above 0 means the figure is missing some spend.

Example call and result, from a test server on a temporary data directory holding six sample
calls (agent usage taken from the recorded `tests/fixtures/agent_fast.json`, one search priced from
the documented table, one failed call, one search with an unknown cost). Real totals will differ:

```json
{"name": "perplexity_usage", "arguments": {"group_by": "tool", "limit": 5}}
```

```json
{
  "totals": {"calls": 6, "errors": 1, "input_tokens": 10278, "output_tokens": 90,
             "total_tokens": 10368, "cost_nano_usd": 8750000, "cost_usd": "0.00875",
             "calls_cost_computed": 1, "calls_cost_unknown": 2},
  "group_by": "tool",
  "groups": [
    {"key": "perplexity_search", "calls": 2, "errors": 0, "input_tokens": 0, "output_tokens": 0,
     "total_tokens": 0, "cost_nano_usd": 5000000, "cost_usd": "0.005",
     "calls_cost_computed": 1, "calls_cost_unknown": 1},
    {"key": "perplexity_agent", "calls": 4, "errors": 1, "input_tokens": 10278,
     "output_tokens": 90, "total_tokens": 10368, "cost_nano_usd": 3750000,
     "cost_usd": "0.00375", "calls_cost_computed": 0, "calls_cost_unknown": 1}
  ],
  "groups_total": 2,
  "groups_truncated": false,
  "project": null, "since": null, "until": null, "limit": 5
}
```

The text content of the same result:

```
Usage: 6 call(s), 1 error(s), 10368 token(s), cost 0.00875 USD (8750000 nano-USD).
The cost is a lower bound: error calls count cost 0 and may have been billed; 2 call(s) have no known cost and 1 cost(s) were computed from documented prices.
By tool: key | calls | errors | tokens | cost USD
perplexity_search | 2 | 0 | 0 | 0.005
perplexity_agent | 4 | 1 | 10368 | 0.00375
```

### `perplexity_projects`

Projects group what the server stores. Later tools create a project the first time they
name one and use the project `default` when none is given; this tool only looks projects up and
never creates one. Project names are case-sensitive, 1 to 64 characters of ASCII letters, digits,
`-`, `_` and `.`, may not begin with `.`, and may not look like an API key.

| Argument | Type | Meaning |
|---|---|---|
| `action` | `list` or `delete` | Required. `list` shows all projects; `delete` removes one |
| `project` | string | Project name (`delete` only) |
| `confirm` | boolean | Must be `true` for `delete`; deletion cannot be undone |

Output: `action`; for `list`, `projects` (each with `name` and `created_at`, UTC); for `delete`,
`project`, `rows_removed` and `rows_retained`. `rows_removed` counts rows removed from tables that
reference the project directly (rows two levels down go by cascade and are not counted).

**Deleting a project keeps its spend history.** Usage events are not deleted: each is detached from
the project (its project reference is cleared) and kept, together with the project's name as it was
written, so `perplexity_usage` still reports that spend under the deleted name. `rows_retained`
counts the events detached. Everything else stored in the project is removed. The project
`default` may be deleted; it is recreated the first time a later tool stores records in it.
Because no 2.0.0 tool stores records yet, a fresh install lists no projects.

```json
{"name": "perplexity_projects", "arguments": {"action": "list"}}
```

```json
{"action": "list", "projects": [{"name": "demo", "created_at": "2026-10-09T19:32:31Z"},
                                {"name": "research", "created_at": "2026-10-09T19:32:31Z"}],
 "project": null, "rows_removed": null, "rows_retained": null}
```

```json
{"name": "perplexity_projects", "arguments": {"action": "delete", "project": "demo", "confirm": true}}
```

```json
{"action": "delete", "projects": null, "project": "demo", "rows_removed": 0, "rows_retained": 3}
```

The spend of the deleted project is still there:

```json
{"name": "perplexity_usage", "arguments": {"project": "demo", "group_by": "project"}}
```

reports `totals.calls` 3 and `totals.cost_usd` `"0.0025"` under the group key `demo`.

## Errors

Every tool failure is an MCP tool error (`isError: true`) in exactly one of eleven categories. A
client can read the category three ways:

- `structuredContent.category` (with `structuredContent.message`), for code
- `_meta.category`, for code that only looks at metadata
- the text content, which always starts `[category] message`, for clients that show only text

```json
{"isError": true,
 "structuredContent": {"category": "confirmation_required",
   "message": "Deleting project 'demo' removes the project and its stored records and cannot be undone; spend history is kept. Call again with confirm=true."},
 "_meta": {"category": "confirmation_required"},
 "content": [{"type": "text", "text": "[confirmation_required] Deleting project 'demo' removes the project ..."}]}
```

| Category | Meaning |
|---|---|
| `invalid_request` | A missing or mistyped argument, an invalid project name, or HTTP 400/422 from the API |
| `authentication` | The API rejected the key (HTTP 401) |
| `forbidden` | The key is not allowed to do this (HTTP 403) |
| `not_found` | Unknown tool, a project that does not exist, or HTTP 404 from the API |
| `rate_limited` | HTTP 429 after the allowed attempts, or at once when `Retry-After` exceeds `PERPLEXITY_MAX_RETRY_WAIT` |
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

**Downgrading drops spend history.** Revision `0002` creates the `usage_events` table. A downgrade
of `0002` (migration code only; the server never downgrades by itself) drops that table and every
usage event in it. A downgrade first writes `backup-0002.db` (the backup is named for the revision
being left), and that file holds the `usage_events` table and its rows: restoring it with the steps
above brings the history back. Another downgrade of the same revision replaces that file, so copy
it somewhere safe first. The upgrade backup, `backup-0001.db`, holds no usage rows, and a fresh
install has no backup at all, because only a database that already has a recorded revision is
backed up.

Use your own `PERPLEXITY_DATA_DIR` in the paths if you set one. Both server processes (a pm2 HTTP
instance and a stdio instance) may share one data directory.

## Development

```bash
uv sync                              # install runtime and dev dependencies from uv.lock
uv run pytest                        # offline test suite (about 40 s)
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
  usage.py        usage recorder (record_usage), money helpers, the Agent usage parser
  pricing.py      documented Perplexity prices in nano-USD, for costs the API does not report
  usage_report.py read-only spend report behind perplexity_usage
  storage/        engine, unit_of_work session, migration runner, project rules, ORM models
  migrations/     Alembic environment and versions/NNNN_slug.py (packaged in the wheel)
  log_setup.py, redaction.py   stderr logging with secrets removed
tests/            offline tests, fixtures/, and the live-marked capture helper
openspec/         the spec-driven change records (py-foundation, py-usage-log)
```

Contributor and agent guidance is in `CLAUDE.md`.

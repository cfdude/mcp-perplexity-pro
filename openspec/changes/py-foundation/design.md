# Design

## Context

See `proposal.md` for motivation and `specs/` for requirements. State that shapes the approach:

- All Sonar endpoints return 403 today, so there is no working behavior to preserve; the TypeScript tree is deleted, not ported.
- Live probes on 2026-10-06 disagree with the docs in two places: `GET /v1/models` needs auth (docs: no auth) and returns per-model `pricing` (docs: no prices). Shapes come from recorded fixtures, not from the docs or OpenAPI.
- FastMCP 4.0.11 resolves `mcp 2.3.0` and depends on `httpx2` (not `httpx`), `pydantic>=2.12`, `pydantic-settings`, `uvicorn`. Its 4.x `Client` speaks the sessionless `2026-07-28` protocol, while the server also serves the legacy stateful `2025-06-18` era. Which era Claude Code uses is not verified.
- The dev machine runs Python 3.14.8 and uv 0.12.23. FastMCP behavior was verified on 3.12.15 only.
- No SQLAlchemy session convention exists in the house conventions; this change proposes one.

## Goals / Non-Goals

**Goals:**
- A running, supervised Python server whose first tool works end to end against the real API, proving transport, config, client, storage and tool schema before any Agent logic is built.
- One place each for: tool registration, model data, HTTP behavior, error mapping, DB sessions.
- Tests that run offline and fast, so the pre-commit hook is tolerable.

**Non-Goals:**
- Agent, Search, Embeddings and Decisions tools, usage logging and routing (their own epics).
- Publishing to PyPI. This change only makes the package build and run via `uvx --from .`; publishing needs credentials and a name check, and is a follow-up.
- Docker and Smithery packaging (dropped; revisit on demand).
- Porting any TypeScript behavior or data.

## Decisions

**D1. Layout and naming.** `src/mcp_perplexity_pro/` with `settings.py`, `errors.py`, `client.py`, `models/` (API payloads), `catalog.py`, `storage/` (ORM, session, migrations runner), `tools/` (one module per tool), `server.py` (`build_server()`), `__main__.py`. Console script `mcp-perplexity-pro`. Migrations live inside the package at `src/mcp_perplexity_pro/migrations/` so a wheel carries them.
*Alternative:* root-level `alembic/` directory. Rejected: it does not ship in a wheel, which breaks `uvx`.

**D2. `build_server(settings, http, engine)` factory.** The server is built from injected dependencies and holds them in a lifespan dataclass reached through `ctx.lifespan_context`. Production wires real ones; tests pass an `httpx2.AsyncClient` on a `MockTransport` and a temp-file engine.
*Alternative:* module-level globals. Rejected: they make tests mutate shared state and hide the startup/teardown path that the spec requires to be tested.

**D3. HTTP client is `httpx2`, used directly.** FastMCP already installs it, so it adds no dependency. Tests inject `httpx2.MockTransport`. `respx` and `pytest-httpx` do not intercept `httpx2` (verified), so they are not used.
*Alternative:* add classic `httpx` plus `respx`. Rejected: two HTTP stacks in one process for no gain.

**D4. Retry is a small loop in `client.py`, not a library.** It encodes two specific rules (retry 429 honoring `Retry-After`; never retry a create POST after any other HTTP response or after a timeout once the request was sent), which a generic retry decorator would make easy to get wrong.

**D5. Tolerant payload models.** API payloads are pydantic models with `extra="allow"` and optional fields by default; a field a caller depends on is checked at the call site and raises the unexpected-response error naming endpoint and field. Fixtures from the probes define the models, not the docs.

**D6. Errors.** `client.py` raises a `PerplexityError` hierarchy matching the spec's categories. Tools convert them to `ToolError` with a sanitized message; the server is built with `mask_error_details=True` so any unexpected exception cannot leak SQL, URLs or keys. The API key is a `SecretStr`. Upstream error text is redacted (configured key and key-shaped tokens) before it is stored, logged or returned, because an upstream message could echo a submitted key; a logging filter is defense in depth. Messages are never built from request headers.

**D7. Settings.** One `pydantic-settings` class, `env_prefix="PERPLEXITY_"` (`PERPLEXITY_API_KEY` and `PERPLEXITY_BASE_URL` match the official MCP server's names), `extra="ignore"`, no `.env` file read. Our variables never use the `FASTMCP_` prefix, which FastMCP reads itself (`FASTMCP_PORT` and a `.env` in the working directory both change its behavior, verified).

**D8. HTTP mode is stateless.** `stateless_http=True`. Stateless mode works with both protocol eras (verified with a legacy raw client and the 4.x `Client`), survives restarts and needs no idle-session cleanup, which retires the old server's session timer. Consequence: nothing may depend on `ctx.session_id`. Two things the design relies on are not yet verified under stateless mode and are checked in the spike (task 3.1) before storage is built: that the lifespan is entered once rather than per request, and that a raising tool reaches dependency teardown so the session rolls back. The loopback default host, plus FastMCP's `http_host_origin_protection`, guards the unauthenticated endpoints; the setting's behavior is also checked in the spike.

**D9. Health and version.** `GET /health` via `@mcp.custom_route`. Version comes from `importlib.metadata.version("mcp-perplexity-pro")` and is set on the server (constructor argument if the spike in task 3.1 shows it is supported, otherwise set on the underlying server object); `/health` and `initialize` read the same value.

**D10. Storage and sessions.** SQLAlchemy 2.0 async with `aiosqlite`; `PRAGMA journal_mode=WAL`, `busy_timeout`, `foreign_keys=ON` set on connect. House convention proposed here: one `AsyncSession` per tool call from a dependency, committed when the tool returns, rolled back on any exception; write transactions begin with `BEGIN IMMEDIATE` (a read-then-write transaction in WAL mode fails at once with BUSY and ignores the busy timeout), and get-or-create is an upsert so concurrent first creates cannot violate uniqueness. Migrations run with a synchronous engine before the async engine starts, under a file lock (a lock file in the data directory, bounded wait of 60 seconds) so the pm2 HTTP process and a stdio instance sharing the data directory cannot migrate at once; a database with a recorded revision is copied to a revision-named backup first using SQLite's online backup API (a plain file copy can be inconsistent while another process holds WAL content), and a failed migration restores from it or runs in a transactional-DDL migration; startup compares the DB revision with the script head and refuses a database newer than the code. Files are `NNNN_slug.py`, each with a working `downgrade()`.
*Alternative:* tool code opens its own sessions. Rejected: it makes the spec's all-or-nothing rule depend on every author remembering.

**D11. Catalog.** `catalog.py` holds the TTL cache (default 3600 s) and the stale-on-failure rule. The preset table is a constant dated 2026-10-06, returned under `source: "documentation"`; it is never mixed into the live list because presets are dynamic and unversioned.

**D12. Tool names and count.** Prefix `perplexity_`. This change adds `perplexity_models` and `perplexity_projects`; later epics add the rest. Target for 2.0 is about nine tools in total, each with typed `Annotated[..., Field(description=...)]` parameters and an output model, since every tool schema costs context in every session.

**D13. `fastmcp-tasks` is not used.** Background jobs will persist the Perplexity response id in SQLite and poll Perplexity (`py-agent-api`). The extension adds Docket, optional Redis and an encryption key, runs work inside our own process rather than a remote one, and is bypassed by legacy-era clients (verified: a `task=True` tool ran synchronously for a `2025-06-18` client).

**D14. Quality gates.** `.pre-commit-config.yaml` runs `ruff-check --fix` and `ruff-format` from the pinned `ruff-pre-commit` repo, plus a local `uv run pytest` hook with `always_run` and `pass_filenames: false`. CI runs `uv sync --locked` (`--frozen` would not detect a stale lock), `ruff check`, `ruff format --check`, `pytest`. pytest config lives in `pyproject.toml`: `asyncio_mode = "auto"`, `testpaths = ["tests"]`, a registered `live` marker, `addopts = "-m 'not live'"`, and FastMCP deprecation warnings turned into errors so version drift is caught early.

**D15. Fixtures.** Probe outputs from 2026-10-06 (`/v1/models`, a `fast` run, a background submit and poll, the two Sonar 403s, the Anthropic `max_output_tokens` 400) are scrubbed and committed under `tests/fixtures/` with a `.meta.json` sidecar recording endpoint and capture date. A test scans them for key-shaped strings.

**D16. Cutover.** Python scaffolding lands first; then one commit deletes the TypeScript sources, npm/Smithery/Docker files, `bin/`, stray logs and backups, and the Node CI jobs. The org security workflow stays. `ecosystem.config.cjs` stays gitignored; a key-free `ecosystem.example.cjs` is committed. Rollback is `git revert` of the cutover commit, though nothing it removes currently works.

## Risks / Trade-offs

- **FastMCP 4 is new and moving** (deprecations already visible, such as `inputSchema` and `Client("script.py")`) → pin `fastmcp>=4.0.11,<5`, treat its deprecation warnings as test errors, and keep FastMCP-specific code in `server.py` and `tools/`.
- **uvicorn may re-raise the signal after shutdown**, so the process could end signal-killed instead of exiting 0 → the spike records the exit status and the shutdown spec is amended before group 6 if needed.
- **Python 3.14 is untested for this stack** (greenlet, `aiosqlite`, FastMCP verified on 3.12 only) → the suite runs on 3.12 and 3.14 in CI; the floor stays 3.12.
- **Real MCP clients are unverified** (era, stateless behavior) → acceptance includes you reconnecting Claude Code and calling `perplexity_models`; that is a manual gate.
- **Docs and live API disagree** → fixtures are the source of truth, `live` tests detect drift when run on demand.
- **Stateless HTTP forgoes server-initiated messages** (sampling, progress to a persistent stream) → none are needed by planned tools; revisit if a tool needs them.
- **SQLite under parallel tool calls** → WAL plus `busy_timeout`, and a 20-writer test enforces the spec scenario.
- **`fastmcp` may write under `~/Library/Application Support/fastmcp`** (`settings.home`, unchecked) → task 6.4 checks it; harmless if it is only a cache, but it must not contain prompts or the key.
- **Deleting TypeScript on this branch is irreversible only by history** → low risk, since every Sonar-backed tool is already returning 403.

## Migration Plan

1. Land Python scaffold and gates on `python-rewrite`; deploy nothing.
2. Land client, catalog and storage with tests.
3. Cut over: delete TypeScript, update docs, swap the pm2 entry, register the port in `~/SERVER_PORTS.md`.
4. You reconnect the MCP server in Claude Code; call `perplexity_models` and `perplexity_projects list`.
5. Merge to `main` only after Gate 2 review and your acceptance. Rollback: restore the previous pm2 entry (not running today) and revert the merge.

## Open Questions

- Whether `mcp-perplexity-pro` is free on PyPI (affects the follow-up publish epic only).
- Whether to add a Docker image later (no current consumer).

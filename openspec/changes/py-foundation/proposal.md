# Proposal

## Why

Every Sonar endpoint this server calls now returns `403 chat_completions_not_available` ("Sonar is now the Agent API"), verified live on 2026-10-06 against both `POST /chat/completions` and `GET /async/chat/completions`. The 1.3.1 TypeScript server therefore cannot answer a single query. Fixing it in place would mean rewriting its client, response types, tool schemas and model list, which are duplicated across five server files and about 25 hardcoded model lists, so we rebuild on the stack we standardise on (Python, uv, FastMCP, pydantic, SQLAlchemy, pytest, ruff) and build the new APIs on a foundation that does not carry that duplication.

## What Changes

- **BREAKING** Replace the TypeScript implementation with a Python 3.12+ package under `src/`, released as 2.0.0. The TypeScript source, npm packaging, Smithery config and Docker files are deleted on the `python-rewrite` branch (git history preserves them). The `.mcp.json` URL does not change: port 8102, path `/mcp`.
- Add a FastMCP server with stdio and Streamable HTTP transports, a `/health` endpoint, and `pydantic-settings` configuration.
- Add one async Perplexity HTTP client (`httpx`) with typed errors, `Retry-After`-aware retry on 429, and response models that tolerate unknown fields.
- Add the model catalog, backed by live `GET /v1/models` (authenticated, returns per-model pricing), exposed as the first tool, `perplexity_models`. This is the thin vertical slice proving transport, config, client and tool schema end to end.
- Add SQLAlchemy 2.0 + SQLite persistence with Alembic (`0001_` naming), a per-call session lifecycle, and a `projects` table. Domain tables (chats, jobs, usage) arrive with the epics that own them.
- Add quality gates: ruff (`line-length = 100`) and pytest as a pre-commit hook, the same checks in CI, a `live` pytest marker excluded by default, and recorded API fixtures captured from the 2026-10-06 probe.
- Run under pm2 with `uv run`, replacing the node entry in the gitignored `ecosystem.config.cjs`, and register the port in `~/SERVER_PORTS.md`.
- Rewrite `CLAUDE.md` and `README.md` for the Python server.

Out of scope here: Agent API tools (`py-agent-api`), Search (`py-search-api`), usage log (`py-usage-log`), Embeddings (`py-embeddings`), Decisions (`py-decisions-tool`), all routing. No data import from `.perplexity/` (clean slate, decided).

## Capabilities

### New Capabilities

- `server-runtime`: FastMCP application, transports, health endpoint, configuration, process lifecycle.
- `perplexity-client`: Authenticated async access to the Perplexity API with error taxonomy, retry and tolerant parsing.
- `model-catalog`: Live list of Agent API models with pricing, served as an MCP tool.
- `local-storage`: SQLite persistence, migrations, project scoping and session handling.
- `quality-gates`: Pre-commit and CI enforcement of ruff and pytest, test layout and fixture rules.

### Modified Capabilities

None. `openspec/specs/` is empty, so every capability above is new.

## Impact

- **Code:** all of `src/` (TypeScript) is removed; new `src/mcp_perplexity_pro/` package, `tests/`, `pyproject.toml`, `uv.lock`, `alembic/`, `.pre-commit-config.yaml`, `.github/workflows/`.
- **Dependencies:** `fastmcp` 4.x (brings `pydantic>=2.12`, `pydantic-settings`, `httpx2`, `uvicorn`; `httpx2` is used directly for the client), `sqlalchemy[asyncio]`, `alembic`, `aiosqlite`; dev: `pytest`, `pytest-asyncio`, `ruff`, `pre-commit`. No `respx` or `pytest-httpx`: neither intercepts `httpx2` (verified), so tests inject `httpx2.MockTransport`.
- **Distribution:** PyPI and `uvx` replace npm and Smithery. Any `npx` consumer breaks.
- **Systems:** pm2 config (local, gitignored), `~/SERVER_PORTS.md`, `.mcp.json` unchanged.
- **Risk carried forward:** `GET /v1/models` requires auth although the docs say it does not, and returns pricing the docs say it omits. The docs and OpenAPI spec are therefore not trusted for shapes; the recorded fixtures are.

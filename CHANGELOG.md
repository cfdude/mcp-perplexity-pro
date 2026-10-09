# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-10-09

### Changed

- **BREAKING** Rewrote the server in Python (FastMCP, SQLAlchemy 2.0 async with SQLite and Alembic, httpx2, pytest, ruff). Perplexity retired its Sonar endpoints (they return `403 chat_completions_not_available`), so the 1.x tools could no longer answer any query. The TypeScript source, npm packaging, Smithery and Docker files are removed.
- Seven tools are available in this release: the four Agent API tools below, plus `perplexity_models` (live model list with prices), `perplexity_projects` (list and confirmed delete) and `perplexity_usage` (spend report). The Search, Embeddings and Decisions tools follow in later releases.
- Data is kept in one SQLite file under `~/.perplexity-pro/`. Nothing is imported from the old `.perplexity/` folders.
- Tool failures carry a stable `category` (eleven values) in structured content.
- The HTTP endpoint is still `http://localhost:8102/mcp`; it listens on 127.0.0.1 only and is stateless.
- `perplexity_projects` `delete` now keeps spend history: usage events are detached from the deleted project and stay reportable by its name, and the result reports them as `rows_retained` next to `rows_removed`. The confirmation message says so.

### Added

- A `usage_events` table (migration `0002`) that keeps one row per costed upstream call: tool, API, model, preset, status, latency, token counts, cost in integer nano-USD, where the cost came from (`reported`, `computed` or `none`) and the project name as written. Downgrading `0002` drops the table and its history.
- A best-effort usage recorder (`record_usage`) for the Agent, Search, Embeddings and Decisions tools to call after each upstream call. It never raises an error (a cancellation is re-raised after the write lands), stores one row per successful response, removes secrets before storing, and survives a rollback of the tool's own writes. `pricing.py` holds Perplexity's documented prices (dated 2026-10-09) for calls whose response carries no cost. The four Agent tools record their usage; the Search, Embeddings and Decisions tools will record theirs when they arrive.
- `perplexity_ask`: one synchronous, web-grounded question with its sources, a usage summary with an exact USD cost string and the measured latency. Depth `fast` (default), `low` or `medium`, or an explicit model; search filters (domains, recency, dates, country, result count), instructions, an output-token cap and structured output. Filters and dates are validated locally because the API accepts some invalid input silently.
- `perplexity_chat`: `send`, `list`, `read` and `delete` over a local chat history. A turn continues from the previous response id; `replay` resends the stored history when the provider cannot continue.
- `perplexity_research`: starts a background research run (`medium`, `high` or `xhigh`) and returns a job id at once. `high` and `xhigh` exist only here because they can cost dollars and take minutes. There is no spending cap.
- `perplexity_jobs`: `list` (with `refresh` to settle running jobs), `status`, `result` and `cancel` over the local job rows. A background run is recorded as spend when a call first sees it finish, once; a run nobody observes is never recorded.
- Three tables, project-scoped with `ON DELETE CASCADE`: `chats` and `chat_messages` (migration `0003`) and `research_jobs` (migration `0004`). Both migrations are reversible, and a downgrade drops the rows (the pre-migration backup, `backup-<rev>.db`, holds them). `perplexity_projects` `delete` reports `running_jobs`: deleting a project with unfinished research runs discards their rows, so their spend is never recorded while the provider keeps running them.
- Setting `PERPLEXITY_AGENT_READ_TIMEOUT` (default 120 seconds): how long a synchronous Agent run (`perplexity_ask`, `perplexity_chat` send) may take.
- `perplexity_usage`: a read-only spend report with exact totals over every matching call plus one grouping (`tool`, `api`, `model`, `project` or `day`), filtered by project and UTC date range. Costs are exact decimal USD strings and a lower bound: `calls_cost_unknown` counts calls whose cost is not known.

### Fixed

- A unit of work that is cancelled mid-block (a client dropping a request) now returns its database connection: the rollback and close run as their own shielded task, because FastMCP and anyio cancel with a level-triggered scope that cut the bare cleanup short and left the connection checked out until garbage collection.

## [1.3.1] - 2026-01-26

### Fixed

- **Async job polling**: Workaround for Perplexity API bug where GET endpoint returns stale `IN_PROGRESS` status while LIST endpoint shows correct `COMPLETED` status
- **Job list parsing**: Fixed `listAsyncJobs` to properly map `requests` → `jobs` from API response
- **API limit bug**: Changed LIST endpoint limit from 50 to 10 due to Perplexity API bug where higher limits return fewer results

## [1.3.0] - 2025-12-22

### Added

- `check_async_perplexity`: New `include_content` parameter (default: `false`) to control whether full response content is returned, saving context for large research reports
- `check_async_perplexity`: New `save_report` parameter (default: `true`) to automatically save completed research reports
- `check_async_perplexity`: New `project_name` parameter for specifying where to save reports
- `check_async_perplexity`: Returns `report_path` when job completes, showing where report was saved

### Changed

- `research_perplexity`: `save_report` now defaults to `true` (previously required explicit opt-in)
- Updated to MCP SDK 1.25.1 for improved compatibility
- Removed deprecated `sonar-reasoning` model references

### Fixed

- `research_perplexity` now properly returns results through HTTP transport (was returning empty)
- Deep research with `sonar-deep-research` model now uses async API with polling to handle long-running queries
- Storage tests no longer have race conditions when running in parallel
- Resolved all Dependabot security alerts

## [1.2.0] - 2025-09-16

### Added

- **Transport Mode Arguments**: New `--transport` argument for explicit deployment mode control
  - `--transport=stdio`: Force stdio transport mode
  - `--transport=http`: Force HTTP transport mode
  - `--transport=auto`: Auto-detect transport mode (default)
- **Unified NPX Usage**: Single `mcp-perplexity-pro` package works for all deployment modes
- **Auto-detection**: Intelligent stdio/HTTP mode detection based on environment
- **Enhanced Help**: Comprehensive help text with transport mode examples
- **Backward Compatibility**: Existing `mcp-perplexity-pro-stdio` binary still supported

### Changed

- **README.md**: Updated with new transport argument examples and usage patterns
- **Default Behavior**: Auto-detect mode is now default, choosing best transport for environment
- **Documentation**: Enhanced deployment examples showing transport mode usage

### Fixed

- **NPX Configuration**: Users can now use `npx mcp-perplexity-pro --transport=stdio` in MCP configs
- **Deployment Flexibility**: Single package name works across all transport modes

## [1.1.0] - 2025-01-29

### Added

- **stdio-npx deployment support**: New `mcp-perplexity-pro-stdio` binary for NPX-based deployments
- **stdio-docker deployment support**: Docker container with stdio transport via `Dockerfile.stdio`
- NPX deployment option with `npx mcp-perplexity-pro-stdio` command
- Docker stdio service in docker-compose.yml with profile support
- Comprehensive deployment documentation for both stdio-npx and stdio-docker
- Docker stdio entrypoint script with environment validation

### Changed

- Updated README.md with detailed deployment instructions for all transport options
- Enhanced package.json with stdio binary and Docker build scripts
- Improved Docker Compose configuration with multiple service profiles

## [1.0.0] - 2025-08-25

### Changed

- **BREAKING CHANGE**: Migrated from stdio to HTTP-only transport
- Unified launcher that works with both Claude Code and Claude Desktop
- Simplified configuration with automatic build detection

### Added

- Universal launcher (`src/launcher.ts`) with automatic build detection
- Shared server logic (`src/mcp-server.ts`) for code reuse
- NPM package structure with bin field for global installation
- HTTP transport configuration for both clients

### Removed

- stdio transport support (deprecated by Anthropic)
- Separate server implementations for different transports

### Fixed

- Alignment with Anthropic's direction away from stdio transport
- Simplified port management and configuration

## [0.1.0] - Previous Version

- Initial implementation with dual stdio/HTTP transport support

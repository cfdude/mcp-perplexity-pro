# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-10-09

### Changed

- **BREAKING** Rewrote the server in Python (FastMCP, SQLAlchemy 2.0 async with SQLite and Alembic, httpx2, pytest, ruff). Perplexity retired its Sonar endpoints (they return `403 chat_completions_not_available`), so the 1.x tools could no longer answer any query. The TypeScript source, npm packaging, Smithery and Docker files are removed.
- Only three tools are available in this release: `perplexity_models` (live model list with prices), `perplexity_projects` (list and confirmed delete) and `perplexity_usage` (spend report). The Agent, Search, Embeddings and Decisions tools follow in later releases.
- Data is kept in one SQLite file under `~/.perplexity-pro/`. Nothing is imported from the old `.perplexity/` folders.
- Tool failures carry a stable `category` (eleven values) in structured content.
- The HTTP endpoint is still `http://localhost:8102/mcp`; it listens on 127.0.0.1 only and is stateless.

### Added

- A `usage_events` table (migration `0002`) that keeps one row per costed upstream call: tool, API, model, preset, status, latency, token counts, cost in integer nano-USD, where the cost came from (`reported`, `computed` or `none`) and the project name as written. Downgrading `0002` drops the table and its history.
- A best-effort usage recorder (`record_usage`) for the Agent, Search, Embeddings and Decisions tools to call after each upstream call. It never raises, stores one row per successful response, removes secrets before storing, and survives a rollback of the tool's own writes. `pricing.py` holds Perplexity's documented prices (dated 2026-10-09) for calls whose response carries no cost. No tool records usage yet; recording arrives with each later tool.
- `perplexity_usage`: a read-only spend report with exact totals over every matching call plus one grouping (`tool`, `api`, `model`, `project` or `day`), filtered by project and UTC date range. Costs are exact decimal USD strings and a lower bound: `calls_cost_unknown` counts calls whose cost is not known.

### Changed (usage)

- `perplexity_projects` `delete` now keeps spend history: usage events are detached from the deleted project and stay reportable by its name, and the result reports them as `rows_retained` next to `rows_removed`. The confirmation message says so.

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

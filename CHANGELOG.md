# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-10-09

### Changed

- A call to `perplexity_ask` or `perplexity_chat` that names no `depth`, `tier` or `model` now uses `perplexity/sonar` with web search instead of the `fast` preset. In one pair of acceptance calls it cost $0.00336 against $0.00124 for `fast`; pass `depth: "fast"` or set `PERPLEXITY_MODEL` to change it. `search` false is now accepted on any model route and is refused only with a `depth`.
- **BREAKING** Rewrote the server in Python (FastMCP, SQLAlchemy 2.0 async with SQLite and Alembic, httpx2, pytest, ruff). Perplexity retired its Sonar endpoints (they return `403 chat_completions_not_available`), so the 1.x tools could no longer answer any query. The TypeScript source, npm packaging, Smithery and Docker files are removed.
- Ten tools are available in this release: the four Agent API tools below, `perplexity_search` (ranked web search results), `perplexity_decide` (calibrated answers to typed questions), `perplexity_embed` (a local vector store searched by meaning), plus `perplexity_models` (live model list with prices), `perplexity_projects` (list and confirmed delete) and `perplexity_usage` (spend report).
- Data is kept in one SQLite file under `~/.perplexity-pro/`. Nothing is imported from the old `.perplexity/` folders.
- Tool failures carry a stable `category` (eleven values) in structured content.
- The HTTP endpoint is still `http://localhost:8102/mcp`; it listens on 127.0.0.1 only and is stateless.
- `perplexity_projects` `delete` now keeps spend history: usage events are detached from the deleted project and stay reportable by its name, and the result reports them as `rows_retained` next to `rows_removed`. The confirmation message says so.

### Added

- Routing modes for `perplexity_ask` and `perplexity_chat` send: `PERPLEXITY_ROUTING` `standard` (default: one model, `perplexity/sonar`, changeable with `PERPLEXITY_MODEL`) or `custom` (three tiers, `PERPLEXITY_TIER_LIGHT`, `PERPLEXITY_TIER_STANDARD` and `PERPLEXITY_TIER_COMPLEX`, picked with a new `tier` argument); `dynamic` is reserved and refused at startup until its classifier ships. The mode is only a default: an explicit `model` is always used as given, and a call naming two of `depth`, `tier` and `model` is refused with a message saying what to do. Every ask and chat result carries a `routing` object (`mode`, `tier`, `model`, `selected_by`), the MCP server `instructions` and the tool descriptions state the configuration, and `perplexity_models` has a `routing` section marking each configured id `known` or not. No migration.
- Result ids on sources: each `sources` entry now carries `ids`, every result id the API gave that URL (at most 64), so an answer marker `[N]` or `[web:N]` finds its source even when a long run returned the same page under several ids (the old digest kept only the first id and dropped the rest). The readable result shows them as `(ids 10, 71)`. In `answer_json`, citation markers that end a string value are removed (one warning gives the count); a value nested deeper than 100 levels is returned as null with a warning. Medium research is documented as $0.016 to $0.025 and 39 to about 90 s over four runs.
- A `usage_events` table (migration `0002`) that keeps one row per costed upstream call: tool, API, model, preset, status, latency, token counts, cost in integer nano-USD, where the cost came from (`reported`, `computed` or `none`) and the project name as written. Downgrading `0002` drops the table and its history.
- A best-effort usage recorder (`record_usage`) for the Agent, Search, Embeddings and Decisions tools to call after each upstream call. It never raises an error (a cancellation is re-raised after the write lands), stores one row per successful response, removes secrets before storing, and survives a rollback of the tool's own writes. `pricing.py` holds Perplexity's documented prices (dated 2026-10-09) for calls whose response carries no cost. The four Agent tools, `perplexity_search`, `perplexity_decide` and `perplexity_embed` record their usage.
- `perplexity_search`: ranked web search results as data (title, url, snippet, dates) from the Search API, with no model answer. Type `fast` (default, $0.001 per request) or `web` ($0.005); one query or up to five, which the API merges into one list that cannot be attributed to a query (the result says so); filters for domains, recency, publication and update dates, languages and country, validated locally because the API accepts some invalid input silently; `max_tokens` and `max_tokens_per_page` caps. The `people` type is not offered. The cost is computed from the documented prices, one unit per request, and recorded like the Agent tools' calls. No new setting and no migration.
- `perplexity_decide`: typed questions about a text, answered with calibrated probabilities from the Decisions API (`POST /v1/decisions`). The state is text or a JSON object or list (at most 200000 characters serialized, no images in this version); 1 to 32 questions per call, each `noul` (a yes probability), `choice` (the most probable option with every option's probability) or `score` (a probability-weighted position on an ordered rubric); model `pplx-decider-v1.1-27b` (default) or `pplx-decider-v1-27b`. The answers are model probabilities, not facts. The cost is computed from input tokens at the documented $0.02 per million (output is free; 20 nano-USD per input token), an unreadable token count is an unknown cost rather than zero, and each request is recorded like the Agent tools' calls (the response carries no request id, so identical calls each record an event). Everything is validated locally, so a bad call is refused before anything is sent or billed. No new setting and no migration.
- `perplexity_embed`: indexes saved chat messages, completed research reports or texts you pass as vectors in the local database and searches them by meaning, with the Embeddings API (`POST /v1/embeddings`). Four actions: `index`, `search`, `status` and `delete` (needs `confirm`). Models `pplx-embed-v1-0.6b` (default, $0.004 per million tokens) and `pplx-embed-v1-4b` ($0.03); `dimensions` a multiple of 8 (128 to 1024, or 2560 for the 4b model); `encoding` `int8` (default) or `binary`. `index` sends the chunk text to Perplexity (the configured key is replaced by `[redacted]` first), embeds only items with no stored vector for the chosen model, size and encoding, and is bounded and resumable: `limit` (default 256) and a `remaining` count to loop on, in batches of at most 64 inputs and 100000 characters, chunks of at most 4000 characters. `search` scores locally (cosine on `int8`, `1 - hamming / dimensions` on `binary`) and returns hits with the chunk text cut to 800 characters; vectors are never returned, and a search with nothing indexed makes no request. The API reports each request's cost, so the cost is recorded as `reported` (a computed fallback from the documented price applies when a response reports none) and each request is one usage event with no request id. No new setting.
- Migration `0005` creates `embedding_chunks`, a project-scoped table (a project holds at most 20000 chunks per model, size and encoding), with `ON DELETE CASCADE` to chat messages and research jobs too, so deleting a chat, a research job or a project removes its vectors. The upgrade of a `0004` database writes `backup-0004.db` first, and a downgrade drops the table and its vectors (`backup-0005.db` holds them).
- `numpy` is a new runtime dependency (floor 2.3.2), used only to score a search and imported lazily. `usage_from_embeddings_response`, the second usage parser (after the Agent one), reads the reported cost and joins the recorder's registry for the `embeddings` API.
- `costed.costed_call`: the one costed-call sequence (validate the project name, commit the project, timed call with no write unit, record), now shared by the Agent, Search, Decisions and Embeddings tools, and `costed.cost_fields`, shared by the search and decide tools.
- `perplexity_ask`: one synchronous, web-grounded question with its sources, a usage summary with an exact USD cost string and the measured latency. Depth `fast` (default), `low` or `medium`, or an explicit model; search filters (domains, recency, dates, country, result count), instructions, an output-token cap and structured output. Filters and dates are validated locally because the API accepts some invalid input silently.
- `perplexity_chat`: `send`, `list`, `read` and `delete` over a local chat history. A turn continues from the previous response id; `replay` resends the stored history when the provider cannot continue.
- `perplexity_research`: starts a background research run (`medium`, `high` or `xhigh`) and returns a job id at once. `high` and `xhigh` exist only here because they can cost dollars and take minutes. There is no spending cap.
- `perplexity_jobs`: `list` (with `refresh` to settle running jobs), `status`, `result` and `cancel` over the local job rows. A background run is recorded as spend when a call first sees it finish, once; a run nobody observes is never recorded.
- Three tables, project-scoped with `ON DELETE CASCADE`: `chats` and `chat_messages` (migration `0003`) and `research_jobs` (migration `0004`). Both migrations are reversible, and a downgrade drops the rows (the pre-migration backup, `backup-<rev>.db`, holds them). `perplexity_projects` `delete` reports `running_jobs`: deleting a project with unfinished research runs discards their rows, so their spend is never recorded while the provider keeps running them.
- Database writes run in a unit of work that survives cancellation: a unit that is cancelled mid-block (a client dropping a request) returns its database connection, because the rollback and close run as their own shielded task (FastMCP and anyio cancel with a level-triggered scope that would cut a bare cleanup short). The writes that follow a provider call that was accepted or billed are shielded too, so a client cancel cannot lose them: the usage recorder, the research submit's job row, the chat turn after a billed send, a billed embedding batch's chunk write, a job's observation update and `cancel_requested_at`.
- Setting `PERPLEXITY_AGENT_READ_TIMEOUT` (default 120 seconds): how long a synchronous Agent run (`perplexity_ask`, `perplexity_chat` send) may take.
- `perplexity_usage`: a read-only spend report with exact totals over every matching call plus one grouping (`tool`, `api`, `model`, `project` or `day`), filtered by project and UTC date range. Costs are exact decimal USD strings and a lower bound: `calls_cost_unknown` counts calls whose cost is not known.

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

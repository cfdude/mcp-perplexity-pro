# Design

## Context

See `proposal.md` for motivation and `specs/` for requirements. State that shapes the approach:

- All Sonar endpoints return 403 today, so there is no working behavior to preserve; the TypeScript tree is deleted, not ported.
- Live probes on 2026-10-06 disagree with the docs in two places: `GET /v1/models` needs auth (docs: no auth) and returns per-model `pricing` (docs: no prices). Shapes come from recorded fixtures, not from the docs or OpenAPI.
- FastMCP 4.0.11 resolves `mcp 2.3.0` and depends on `httpx2` (not `httpx`), `pydantic>=2.12`, `pydantic-settings`, `uvicorn`. Its 4.x `Client` speaks the sessionless `2026-07-28` protocol, while the server also serves the legacy stateful `2025-06-18` era. Which era Claude Code uses is not verified.
- The dev machine runs Python 3.14.8 and uv 0.12.23. FastMCP behavior was first verified on 3.12.15 only; the spike (task 3.1) re-ran it on both.
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

**D2. `build_server(settings, http, engine)` factory.** The server is built from injected dependencies and holds them in a lifespan dataclass reached through `ctx.lifespan_context`. Production wires real ones; tests pass an `httpx2.AsyncClient` on a `MockTransport` and a temp-file engine. The caller owns the injected client and engine and closes them in `run()`; the lifespan only exposes them, because FastMCP's lifespan teardown does not run on any signal in stdio mode (see Spike results).
*Alternative:* module-level globals. Rejected: they make tests mutate shared state and hide the startup/teardown path that the spec requires to be tested.

**D3. HTTP client is `httpx2`, used directly.** FastMCP already installs it, so it adds no dependency. Tests inject `httpx2.MockTransport`. `respx` and `pytest-httpx` do not intercept `httpx2` (verified), so they are not used.
*Alternative:* add classic `httpx` plus `respx`. Rejected: two HTTP stacks in one process for no gain.

**D4. Retry is a small loop in `client.py`, not a library.** It encodes two specific rules (retry 429 honoring `Retry-After`; never retry a create POST after any other HTTP response or after a timeout once the request was sent), which a generic retry decorator would make easy to get wrong.

**D5. Tolerant payload models.** API payloads are pydantic models with `extra="allow"` and optional fields by default; a field a caller depends on is checked at the call site and raises the unexpected-response error naming endpoint and field. Fixtures from the probes define the models, not the docs.

**D6. Errors.** `client.py` raises a `PerplexityError` hierarchy matching the spec's categories. `PerplexityError` subclasses `ToolError`, so FastMCP does not mask it, and one server-level middleware turns it into an error result carrying `category` in structured content (encoding in Spike results); the server is built with `mask_error_details=True` so any other exception cannot leak SQL, URLs or keys, and reaches the client as `Error calling tool '<name>'` without a category. The API key is a `SecretStr`. Upstream error text is redacted (configured key and key-shaped tokens) before it is stored, logged or returned, because an upstream message could echo a submitted key; a logging filter is defense in depth. Messages are never built from request headers.

**D7. Settings.** One `pydantic-settings` class, `env_prefix="PERPLEXITY_"` (`PERPLEXITY_API_KEY` and `PERPLEXITY_BASE_URL` match the official MCP server's names), `extra="ignore"`, no `.env` file read. Our variables never use the `FASTMCP_` prefix, which FastMCP reads itself (`FASTMCP_PORT` and a `.env` in the working directory both change its behavior, verified).

**D8. HTTP mode is stateless.** `stateless_http=True`. Stateless mode works with both protocol eras (verified with a legacy raw client and the 4.x `Client`), survives restarts and needs no idle-session cleanup, which retires the old server's session timer. Consequence: nothing may depend on `ctx.session_id`. The spike (task 3.1) verified under stateless mode that the lifespan is entered once and that a raising tool reaches dependency teardown. HTTP mode is run by our own `uvicorn.Server` subclass over `mcp.http_app(path="/mcp", stateless_http=True, json_response=True, host_origin_protection=True)`, not by `mcp.run()`: `mcp.run()` exits 143 on SIGTERM and skips lifespan teardown, and with SSE responses uvicorn aborts in-flight calls at the signal. FastMCP's host/origin protection is OFF by default, so it is enabled explicitly; with the loopback default host it guards `/mcp` and `/health`.

**D9. Health and version.** `GET /health` via `@mcp.custom_route`. Version comes from `importlib.metadata.version("mcp-perplexity-pro")` and is set on the server (constructor argument `FastMCP(version=...)`, verified in the spike to be reported as `serverInfo.version`); `/health` and `initialize` read the same value.

**D10. Storage and sessions.** SQLAlchemy 2.0 async with `aiosqlite`; `PRAGMA journal_mode=WAL`, `busy_timeout`, `foreign_keys=ON` set on connect. House convention proposed here: one `AsyncSession` per tool call from a dependency (an `@asynccontextmanager` function: FastMCP does not manage a bare async generator, and the tool would receive the generator object), committed when the tool returns, rolled back on any exception; write transactions begin with `BEGIN IMMEDIATE` (a read-then-write transaction in WAL mode fails at once with BUSY and ignores the busy timeout), and get-or-create is an upsert so concurrent first creates cannot violate uniqueness. Migrations run with a synchronous engine before the async engine starts, under a file lock (a lock file in the data directory, bounded wait of 60 seconds) so the pm2 HTTP process and a stdio instance sharing the data directory cannot migrate at once; a database with a recorded revision is copied to a revision-named backup first using SQLite's online backup API (a plain file copy can be inconsistent while another process holds WAL content), and a failed migration restores from it or runs in a transactional-DDL migration; startup compares the DB revision with the script head and refuses a database newer than the code. Files are `NNNN_slug.py`, each with a working `downgrade()`.
*Alternative:* tool code opens its own sessions. Rejected: it makes the spec's all-or-nothing rule depend on every author remembering.

**D11. Catalog.** `catalog.py` holds the TTL cache (default 3600 s) and the stale-on-failure rule. The preset table is a constant dated 2026-10-06, returned under `source: "documentation"`; it is never mixed into the live list because presets are dynamic and unversioned.

**D12. Tool names and count.** Prefix `perplexity_`. This change adds `perplexity_models` and `perplexity_projects`; later epics add the rest. Target for 2.0 is about nine tools in total, each with typed `Annotated[..., Field(description=...)]` parameters and an output model, since every tool schema costs context in every session.

**D13. `fastmcp-tasks` is not used.** Background jobs will persist the Perplexity response id in SQLite and poll Perplexity (`py-agent-api`). The extension adds Docket, optional Redis and an encryption key, runs work inside our own process rather than a remote one, and is bypassed by legacy-era clients (verified: a `task=True` tool ran synchronously for a `2025-06-18` client).

**D14. Quality gates.** `.pre-commit-config.yaml` runs `ruff-check --fix` and `ruff-format` from the pinned `ruff-pre-commit` repo, plus a local `uv run pytest` hook with `always_run` and `pass_filenames: false`. CI runs `uv sync --locked` (`--frozen` would not detect a stale lock), `ruff check`, `ruff format --check`, `pytest`. pytest config lives in `pyproject.toml`: `asyncio_mode = "auto"`, `testpaths = ["tests"]`, a registered `live` marker, `addopts = "-m 'not live'"`, and FastMCP deprecation warnings turned into errors so version drift is caught early.

**D15. Fixtures.** Probe outputs from 2026-10-06 (`/v1/models`, a `fast` run, a background submit and poll, the two Sonar 403s, the Anthropic `max_output_tokens` 400) are scrubbed and committed under `tests/fixtures/` with a `.meta.json` sidecar recording endpoint and capture date. A test scans them for key-shaped strings.

**D16. Cutover.** Python scaffolding lands first; then one commit deletes the TypeScript sources, npm/Smithery/Docker files, `bin/`, stray logs and backups, and the Node CI jobs. The org security workflow stays. `ecosystem.config.cjs` stays gitignored; a key-free `ecosystem.example.cjs` is committed. Rollback is `git revert` of the cutover commit, though nothing it removes currently works.

## Risks / Trade-offs

- **FastMCP 4 is new and moving** (deprecations already visible, such as `inputSchema` and `Client("script.py")`) → pin `fastmcp>=4.0.11,<5`, treat its deprecation warnings as test errors, and keep FastMCP-specific code in `server.py` and `tools/`.
- **uvicorn re-raises the signal after shutdown** (verified: exit 143 on SIGTERM) → our `uvicorn.Server` subclass overrides `handle_exit` so the signal is not re-raised and the process exits 0 (Spike results); the override depends on uvicorn's `handle_exit` behavior, so a test pins exit 0 on SIGTERM.
- **Python 3.14 for this stack**: the spike's behaviors and a SQLAlchemy/aiosqlite round trip were identical on 3.12.15 and 3.14.8 → the suite still runs on both in CI; the floor stays 3.12.
- **Real MCP clients are unverified** (era, stateless behavior) → acceptance includes you reconnecting Claude Code and calling `perplexity_models`; that is a manual gate.
- **Docs and live API disagree** → fixtures are the source of truth, `live` tests detect drift when run on demand.
- **Stateless HTTP forgoes server-initiated messages** (sampling, progress to a persistent stream) → none are needed by planned tools; revisit if a tool needs them.
- **SQLite under parallel tool calls** → WAL plus `busy_timeout`, and a 20-writer test enforces the spec scenario.
- **`fastmcp` writes `version_cache.json` under its home directory** (`~/Library/Application Support/fastmcp` on macOS) and checks PyPI for a newer version when its startup banner is shown (verified: no file appears with the banner off) → our runner never shows the banner, and `FASTMCP_CHECK_FOR_UPDATES=off` is a second guard; task 6.4 re-checks with an empty `HOME`.
- **Deleting TypeScript on this branch is irreversible only by history** → low risk, since every Sonar-backed tool is already returning 403.

## Migration Plan

1. Land Python scaffold and gates on `python-rewrite`; deploy nothing.
2. Land client, catalog and storage with tests.
3. Cut over: delete TypeScript, swap the pm2 entry, register the port in `~/SERVER_PORTS.md`. Documentation (`README.md`, `CLAUDE.md`) follows Gate 2.
4. You reconnect the MCP server in Claude Code; call `perplexity_models` and `perplexity_projects list`.
5. Merge to `main` only after Gate 2 review and your acceptance. Rollback: restore the previous pm2 entry (not running today) and revert the merge.

## Open Questions

- Whether `mcp-perplexity-pro` is free on PyPI (affects the follow-up publish epic only).
- Whether to add a Docker image later (no current consumer).

## Observed API shapes

Recorded 2026-10-09 into `tests/fixtures/` (live capture, `tests/test_live_capture.py`; the 2026-10-06 probe outputs named in D15 were re-captured). Nothing account-specific appeared in any payload: `user` and `safety_identifier` are `null`, so the scrub step removed nothing. Response ids (`resp_<uuid>`, `msg_<uuid>`) are kept.

**`GET /v1/models`** (`models.json`, 200; 52 models, 5 providers: anthropic 14, openai 17, google 8, xai 7, perplexity 6)
- Envelope `{"object": "list", "data": [...]}`; each entry has exactly `id`, `object` (`"model"`), `created` (always `0`), `owned_by`, `pricing`.
- Provider is `owned_by` (a lowercase string) and equals the prefix of `id`; every id is `provider/name` (including `perplexity/sonar`), none unprefixed.
- `pricing` is present on all 52 models, so no fixture model lacks pricing; the "model without pricing" spec scenario needs a synthetic entry in tests. Fields: `input`, `output`, `cache_read` (all 52) and `cache_write` (22 of 52: anthropic 14, openai 7, xai 1; absent for google, perplexity and the rest), plus `unit`, always `"usd_per_1m_tokens"`. Values are JSON numbers. Partial pricing therefore means a missing `cache_write` key (30 models), never `null`.
- No preset names (`fast`, `low`, ...) appear in the list, so presets stay a separate documented section.
- Unauthenticated (`models_unauthenticated.json`): 401, body `error.type = "invalid_api_key"`.

**Error body shape** (all four error fixtures): `{"error": {"message": str, "type": str, "code": int}}`.
- `type` is a string name; `code` is the integer HTTP status, not a name. The retired-endpoint name `chat_completions_not_available` is in `type`, and `code` is `403`. The spec said "type or code"; it was amended to `type`.
- Observed types: 401 `invalid_api_key`; 403 `chat_completions_not_available` (both `/chat/completions` POST and `/async/chat/completions` GET, identical bodies; the message says to use `/v1/responses` and links the migration docs); 400 `invalid_request` (the Anthropic case: "max_output_tokens is required when using Anthropic models"). The 400 type string equals our own category name by coincidence; map by status, not by type.
- The client must therefore tolerate `code` being an int and `type` a str, either possibly absent.

**`POST /v1/agent`** (`agent_fast.json`, 200, preset `fast`)
- Returns an OpenAI-Responses-style object: `object: "response"`, `id` `resp_<uuid>`, `status` `"completed"`, `model` is the resolved model (`openai/gpt-6-luna`), not the preset name, `background`, `store: true`, `error: null`, `incomplete_details: null`, `user: null`, `safety_identifier: null`, `tools: []`, plus many echoed request parameters (`temperature`, `top_p`, penalties, `max_output_tokens: null`, ...). Timestamps `created_at` and `completed_at` are integer epoch seconds.
- `output[]` item types seen: `search_results` (keys `queries`, `results`, `type`; no `id`; each result has `date`, `id` (int), `last_updated`, `snippet`, `source`, `title`, `url`) and `message` (`id`, `role`, `status`, `type`, `content[]` of `output_text` parts with `text` and `annotations`). Item types must be treated as an open set.
- `usage`: `input_tokens`, `output_tokens`, `total_tokens`, `input_tokens_details` (`cache_creation_input_tokens`, `cache_read_input_tokens`, `cached_tokens`), `output_tokens_details.reasoning_tokens`, `tool_calls_details.<tool>.{cost_usd, invocation}`, and `cost`.
- `usage.cost` fields: `currency` (`"USD"`), `input_cost`, `output_cost`, `cache_read_cost`, `tool_calls_cost`, `tool_calls_cost_details.<tool>` (e.g. `search_web`), `total_cost`. `cache_creation_cost` appears only when cache was written (present in `agent_fast`, absent in the background poll). Costs are floats in USD; the fast run cost about $0.00125.

**Background run** (`agent_background_submit.json`, `agent_background_poll_pending.json`, `agent_background_poll.json`)
- Submit with `background: true` returns 200 immediately with the same object shape, `status: "queued"`, `output: []`, `usage: null`, `completed_at: null`, `model` still the preset name (`fast`).
- Poll is `GET /v1/agent/{id}` (200 on the first try; the helper would have recorded 404s on an alternative path, and none occurred). Statuses observed: `queued`, `queued`, `completed` (about 4 s). Only `queued` and `completed` were observed; `in_progress`, `failed`, `cancelled` and `incomplete` were not, so the status set is open.
- The completed poll carries the same shape as a synchronous run, with `model` now resolved and `usage` populated.

**Surprises and refinements**
- Docs say `/v1/models` is unauthenticated and price-free; live it needs auth and always has pricing (as D-context already noted, now fixture-backed).
- `created` is `0` for every model, so it cannot order or date models.
- Pricing keys vary per model; a model's `cache_write` absence is the common case (58%), so output models must treat it as optional.
- Capture used no `max_output_tokens` for the Anthropic case and got the 400 above; non-Anthropic `fast` runs need none.

## Spike results

Run 2026-10-09 on CPython 3.12.15 and 3.14.8 with the locked set (fastmcp 4.1.0, mcp 2.3.0, uvicorn 0.54.0, sqlalchemy 2.1.4, alembic 1.20.0, aiosqlite 0.22.1, greenlet 3.5.6, httpx2 2.13.1), in scratch virtualenvs outside the repo, against a throwaway one-tool-plus server. Every row was observed to behave identically on both Python versions. Clients used: raw `httpx2` JSON-RPC at protocol `2025-06-18`, the fastmcp 4.x `Client` (`2026-07-28` era), and a raw stdio pipe.

| | Question | Answer | Evidence |
|---|---|---|---|
| a | stdio and stateless HTTP serve a one-tool server | **Yes** | `mcp.run(transport="stdio")` and `mcp.run(transport="http", ..., stateless_http=True)` and `mcp.http_app(...)` under uvicorn all answered `initialize`, `tools/list`, `tools/call` for both clients; no `mcp-session-id` header is ever issued. `python -m` should use the `http_app` plus own-`uvicorn.Server` form, not `mcp.run()` (row d). |
| b | Lifespan entered once, not per request | **Yes** | 6 stateless requests (3 raw, 3 client) all saw `entries == 1`; one `lifespan_enter` line in the log, entered at app startup before any request. |
| c | A raising tool reaches dependency teardown; `Context` works | **Yes**, with one rule | A `Depends(get_session)` teardown received the original `ValueError` (text included) before FastMCP masked it, so a session can roll back; a clean call ran the `else` branch. `ctx.lifespan_context` is readable in stateless mode. Rule: the dependency must be an `@asynccontextmanager` function. A bare `async def` generator is not managed; the tool gets the generator object. |
| d | Exit status and shutdown hooks on SIGTERM, SIGINT, stdin EOF | **Different from the design** | See the table below. |
| e | Constructor version; host/origin protection | **Yes** / **different** | `FastMCP("n", version="9.8.7")` is reported as `serverInfo.version` to both clients. `http_host_origin_protection` defaults to `False`: with it off a request with `Host: evil.com` or `Origin: http://evil.com` gets 200. Set `host_origin_protection=True` (`http_app` or `run` keyword, or `FASTMCP_HTTP_HOST_ORIGIN_PROTECTION=true`): `Host: evil.com` gives 421, `Origin: http://evil.com` gives 403, `127.0.0.1`, `localhost` and `Origin: http://localhost:3000` give 200, on `/mcp` and on `/health`. `"auto"` behaved the same for a loopback bind. |
| f | Every dependency installs and imports on 3.14 | **Yes** | `uv sync --locked --python 3.14` succeeded; `fastmcp`, `sqlalchemy[asyncio]`, `alembic`, `aiosqlite`, `greenlet` import; an `aiosqlite` create/insert/select round trip passed under `-W error::DeprecationWarning` on both versions. |
| g | `ToolError` reaches the client with a machine-readable `category`; unexpected text hidden | **Yes**, via middleware | See "Error encoding". |

**Row d, observed exit status and teardown** (idle server unless noted):

| Run mode | SIGTERM | SIGINT | stdin EOF |
|---|---|---|---|
| `mcp.run(transport="http")` | exit 143, FastMCP lifespan teardown **not** run | exit 0, teardown runs | n/a |
| `http_app` + `uvicorn.run` | exit 143, teardown runs, code after `run` never executes | exit 0, teardown runs | n/a |
| `http_app` + own `uvicorn.Server` subclass (below) | **exit 0**, teardown runs, code after `serve()` runs | exit 0, teardown runs | n/a |
| `mcp.run(transport="stdio")` | killed by signal (-15), no teardown | **hangs** until SIGKILL (10 s observed; cause not isolated, consistent with a thread blocked reading stdin) | exit 0 in about 0.1 s, teardown runs |
| stdio with loop signal handlers calling `os._exit(0)` after closing resources | exit 0 in 10 ms | exit 0 in 10 ms | exit 0 |

Why: uvicorn's `Server.capture_signals()` records each signal and re-raises it once shutdown completes, so the process dies by signal (143). Under `mcp.run()` FastMCP enters the app lifespan outside `Server.serve()`, so the process dies before that teardown can run. Cancelling the main task from a signal handler also hung (stdio), so only a hard exit after our own cleanup was found to work.

In-flight requests (HTTP, `slow` tool, SIGTERM sent 1 s after the call began, `timeout_graceful_shutdown=10`):
- Default responses are SSE, and `sse-starlette` ends every SSE stream the moment uvicorn's `should_exit` is set. The call is aborted at once ("ASGI callable returned without completing response", client sees an incomplete chunked body) and the process exits within 0.2 s. This holds for all three HTTP run modes.
- With `json_response=True` (plain JSON responses) a 3 s call finishes: the client receives the result 2.1 s after SIGTERM and the process exits 0 at 2.3 s. A 30 s call is cancelled at 10.2 s (client gets HTTP 500, uvicorn logs `CancelledError: Task cancelled, timeout graceful shutdown exceeded`), the lifespan teardown runs, exit 0. `AppStatus.disable_automatic_graceful_drain()` from `sse_starlette.sse` also keeps SSE calls alive (same timings) but `json_response=True` needs no hook.
- Stdio mode: the `os._exit` path above does not wait for an in-flight call. Task 6.4 must add an in-flight counter (middleware) and wait up to 10 s before the hard exit.

**Working snippets**

HTTP runner (exit 0 on SIGTERM and SIGINT, 10 s drain, host/origin guard on):

```python
class _Server(uvicorn.Server):
    # uvicorn's handle_exit also appends to _captured_signals, which capture_signals()
    # re-raises after shutdown; omitting that is what makes the exit status 0.
    def handle_exit(self, sig, frame):
        if self.should_exit and sig == signal.SIGINT:
            self.force_exit = True
        else:
            self.should_exit = True


app = server.http_app(
    path="/mcp", stateless_http=True, json_response=True, host_origin_protection=True
)
config = uvicorn.Config(
    app, host=host, port=port, lifespan="on", timeout_graceful_shutdown=10, log_level=level
)
asyncio.run(_Server(config).serve())  # resources are closed by the caller afterwards
```

stdio runner (exit 0 on EOF, SIGTERM and SIGINT):

```python
async def _run_stdio(server, close_resources):
    loop = asyncio.get_running_loop()

    async def _bye():
        await close_resources()  # log both closures here
        sys.stderr.flush()
        os._exit(0)  # a blocked stdin reader thread would otherwise hang the exit

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_bye()))
    await server.run_stdio_async(
        show_banner=False
    )  # returns on stdin EOF; caller then closes resources
```

Dependency (teardown sees the original exception):

```python
@asynccontextmanager
async def unit_of_work():
    session = ...  # pseudo-code: the verified part is that teardown sees the exception
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
```

**Error encoding.** A tool raising a `ToolError` subclass is the supported path; FastMCP re-raises any `FastMCPError` unmasked, and `str(error)` becomes the text content. By itself that carries no `category` (a plain `ToolError("msg")` arrives as `structuredContent: null`, text `msg`). `ToolResult(is_error=True, content=..., structured_content=..., meta=...)` exists, so one server-level middleware converts the error:

```python
class PerplexityError(ToolError):  # must subclass ToolError, see below
    category: str


class CategoryMiddleware(Middleware):
    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except PerplexityError as e:
            return ToolResult(
                content=f"[{e.category}] {e}",
                structured_content={"category": e.category, "message": str(e)},
                meta={"category": e.category},
                is_error=True,
            )
```

A client reads, on the wire at `2025-06-18` and through the fastmcp `Client` at `2026-07-28`: `isError: true`, `structuredContent: {"category": "not_found", "message": "..."}`, `_meta: {"category": "not_found"}`, and text `[not_found] ...` (the prefix is the fallback for a client that shows only text). The client-side output-schema check is skipped for error results (verified with a tool that has an output schema). Observed limits:
- An exception that is not a `ToolError` is masked **before** middleware runs, so a category on a plain `Exception` subclass is lost: the middleware only sees `ToolError("Error calling tool '<name>'")`. `PerplexityError` therefore subclasses `ToolError`.
- With `mask_error_details=True` an unexpected exception reaches the client as `Error calling tool '<name>'`, no category, no exception text (verified with a `RuntimeError` containing a `pplx-` token). The spec's tool-error requirement was amended to say anticipated failures carry the category.
- FastMCP special-cases an escaping `httpx2` 429 response or timeout and returns its own fixed message ("Rate limited by upstream API...", "Upstream request timed out..."); the client converts these to `PerplexityError` first, so this path must never be reached.
- FastMCP logs the full traceback of an unexpected exception to stderr through its own Rich handler on the `fastmcp` logger, including the source line of the `raise` and the exception text, which can contain a key. The redaction filter (task 3.3) must therefore be attached to FastMCP's handlers too, and must flatten `exc_info` to redacted text so no unredacted traceback is rendered.

**Files created outside the data directory.** With an empty `HOME` and empty working directory, HTTP and stdio runs created nothing. The one exception: when FastMCP's startup banner is shown (the `mcp.run()` default, `show_banner=True`) it checks PyPI for a newer release and writes `~/Library/Application Support/fastmcp/version_cache.json` (macOS; `platformdirs` user data dir elsewhere). `show_banner=False`, or our own runner (which never calls the banner), or `FASTMCP_CHECK_FOR_UPDATES=off` leaves no file. Task 6.4 still records the finding with the final server.

**Amendments made because of the spike**
- D2: caller owns and closes the client and engine; the lifespan only exposes them.
- D6: `PerplexityError` subclasses `ToolError`; category conveyed by middleware; other exceptions are masked without a category.
- D8: own `uvicorn.Server` subclass instead of `mcp.run()`; `json_response=True`; `host_origin_protection=True` set explicitly (it defaults to off).
- D9: version passed to the `FastMCP` constructor (verified).
- D10: session dependency must be an `@asynccontextmanager`.
- Risks: the signal re-raise, Python 3.14 and fastmcp-home bullets updated with the findings.
- `server-runtime` spec, requirement "Tool error contract": anticipated failures carry `category` and `message`; an unexpected exception reaches the client as a generic message (previously "every tool failure" carried a category, which masking makes unmeetable without inventing a category).

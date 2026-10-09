# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

MCP server for the Perplexity API, written in Python (FastMCP, SQLAlchemy 2.0 async, SQLite,
Alembic). Version 2.0.0 replaced the TypeScript 1.x server, which is deleted (git history keeps
it): Perplexity retired the Sonar endpoints (`403 chat_completions_not_available`), so there was
nothing to port. Seven tools exist: the four Agent API tools `perplexity_ask`, `perplexity_chat`,
`perplexity_research` and `perplexity_jobs` (they spend money), plus `perplexity_models`,
`perplexity_projects` and the read-only `perplexity_usage`. The Search, Embeddings and Decisions
tools come in later OpenSpec changes, and each must record its costed calls (see "How to record
usage"); the four Agent tools already record theirs. Read `README.md` for the user-facing behavior
and `openspec/changes/archive/2026-10-09-py-foundation/`,
`openspec/changes/archive/2026-10-09-py-usage-log/` and `openspec/changes/py-agent-api/`
(`design.md` especially) for why things are the way they are.

## Development Commands

Python 3.12+, uv. Never use `pip`, bare `python` or a hand-made venv.

```bash
uv sync                              # install from uv.lock (runtime + dev)
uv run mcp-perplexity-pro --transport stdio    # or: --transport http (127.0.0.1:8102/mcp)
uv run pytest                        # offline suite, about 60 s
uv run pytest tests/test_catalog.py -k stale   # one file / one test
uv run ruff check .                  # lint
uv run ruff format --check .         # formatting (use `uv run ruff format .` to fix)
uv run pre-commit run --all-files    # what the commit hook runs
PERPLEXITY_API_KEY=... uv run pytest -m live   # live tests; real key, never committed
```

- **Ruff is the only linter and formatter** (line length 100, rules E F I UP B). No wrapper scripts.
- **The commit hook** (`.pre-commit-config.yaml`) runs `ruff check --fix`, `ruff format` and
  `uv run --locked pytest`. Never `git commit --no-verify`.
- **`--locked`, not `--frozen`,** wherever the lockfile is a gate (CI, the hook): `--frozen` trusts
  `uv.lock` without comparing it to `pyproject.toml` (`docs/lessons/uv-frozen-does-not-check-the-lock.md`).
  The pm2 start command uses `--frozen` on purpose: it must start, not re-resolve.
- CI (`.github/workflows/ci.yml`): `uv sync --locked`, ruff check, ruff format --check, pytest, on
  Python 3.12 and 3.14.
- Add dependencies with `uv add <pkg>` (updates `pyproject.toml` and `uv.lock` together).

## Architecture Overview

`src/mcp_perplexity_pro/`:

| Module | Role |
|---|---|
| `__main__.py` | Entry point (`main`, `bootstrap`, `run`). Startup order: settings, then data dir and migrations, then upstream client, then listen. Own `uvicorn.Server` subclass for HTTP, own signal handling for stdio |
| `cli.py` | `--transport stdio\|http`, `--version`; parsed before settings so `--help` needs no key |
| `settings.py` | `Settings` (pydantic-settings, prefix `PERPLEXITY_`), `load_settings()` raising `SettingsError` that names each bad variable |
| `server.py` | `build_server(settings, http, engine)`, `AppContext`, `/health`, the two middlewares, `error_result()` |
| `client.py` | `PerplexityClient`: the one httpx2 client, retry loop, typed errors, redacted logging. Agent helpers `create_run` (a synchronous run gets `PERPLEXITY_AGENT_READ_TIMEOUT`), `get_run`, `cancel_run` |
| `errors.py` | `PerplexityError` (a FastMCP `ToolError`), `CATEGORIES`, `ALL_CATEGORIES`, status-to-category mapping |
| `catalog.py` | Model list TTL cache, stale-on-failure rule, the dated `PRESETS` table |
| `models/` | Tolerant pydantic payload models (`extra="allow"`, optional fields) |
| `models/agent.py` | `AgentRun` and `CancelResponse`: only `id` and `status` are required, `output` is `Any`, so a spend-bearing response is never lost to a schema quibble |
| `agent.py` | The Agent toolset's shared logic: option validation and `build_request`, `digest` (answer, sources, usage summary), `run_costed` (the one costed-call sequence, below), and the research job observation (`observe_job`, `job_columns`, `JobLocks`) |
| `tools/` | One module per tool, each `register(server)`; `tools/__init__.py:register_tools` calls them |
| `tools/ask.py`, `tools/chat.py`, `tools/research.py`, `tools/jobs.py` | `perplexity_ask` (stateless, `fast`/`low`/`medium`), `perplexity_chat` (`send`/`list`/`read`/`delete` over local history), `perplexity_research` (background submit, returns a job id), `perplexity_jobs` (`list`/`status`/`result`/`cancel`). Specs: `openspec/changes/py-agent-api/specs/` |
| `usage.py` | The recorder `record_usage` (best effort, never raises), money helpers (`to_nano`, `format_usd`, nano-USD ints), `Usage`/`ToolCallUsage`, `usage_from_agent_response`, `computed_usage`, `agent_response_status`, and the `_PARSERS` registry (one entry per `api`) |
| `pricing.py` | Documented Perplexity prices as integer nano-USD (`PRICES_AS_OF`, `PRICES_SOURCE`) and the `*_cost_nano` helpers returning `None` when unknown; pinned to `tests/fixtures/pricing_page.json` |
| `usage_report.py` | `usage_report`: read-only SQL aggregation behind `perplexity_usage` (totals over all matches, one grouping chosen from a fixed whitelist, bound parameters only) |
| `storage/` | `engine.py` (data dir, engine, PRAGMAs), `session.py` (`unit_of_work`), `migrate.py` (runner), `models.py` (ORM: `Project`, `UsageEvent`, `Chat`, `ChatMessage`, `ResearchJob`), `projects.py` (name rules, get-or-create, delete, the introspection of scoped and retained tables) |
| `storage/chats.py`, `storage/jobs.py` | Row operations for chats (create, append a turn, history, list, read, delete) and research jobs (insert, load, update, list, refresh candidates, `count_running`). They run inside the caller's unit of work and never open one; a vanished row or project is `not_found`, never `storage_busy` |
| `migrations/` | Alembic env and `versions/NNNN_slug.py`; inside the package so the wheel ships them |
| `log_setup.py`, `redaction.py` | stderr-only logging; secrets and `pplx-` tokens removed from every record |

### build_server / lifespan / AppContext

`build_server(settings, http, engine)` takes its dependencies as arguments (design D2). It builds a
`PerplexityClient` and `Catalog`, packs `settings`, `http`, `client`, `engine`, `catalog` into the
frozen `AppContext` dataclass (also `now`, our UTC clock for research jobs, and `job_locks`, one
in-process lock per research job), and exposes it to tools through the FastMCP lifespan, so inside
a tool it is `ctx.lifespan_context`. The server also carries `server.app` (the `AppContext`) and
`server.in_flight` (the draining counter). Ownership rule: **the caller owns `http` and `engine`
and closes them** (`__main__.run` does). The lifespan only exposes them, because FastMCP's
lifespan teardown does not run on a signal in stdio mode. Production wires real ones; tests pass
an `httpx2.AsyncClient` on a `MockTransport` and a temp-file engine. No module-level globals.

HTTP mode is stateless (`stateless_http=True`, `json_response=True`, `host_origin_protection=True`),
so nothing may depend on `ctx.session_id`. Version has one source, `importlib.metadata`, read by
`/health` and the MCP `initialize` result.

### How to add a tool

1. Create `tools/<name>.py` with `register(server)`; register it in `tools/__init__.py`.
2. Name it `perplexity_<name>`. Type every parameter as `Annotated[..., Field(description=...)]`
   and declare an output model: pass `output_schema=Model.model_json_schema()` and return a
   `ToolResult(content=<readable text>, structured_content=model.model_dump(mode="json"))`.
3. Reach dependencies through `ctx.lifespan_context` (`.client`, `.catalog`, `.engine`,
   `.settings`). Never build a client or engine inside a tool.
4. Open the database only with `async with unit_of_work(engine) as session:` (see session
   convention below). A tool that stores records resolves its project with
   `get_or_create_project(session, project)` inside that block.
5. Set `annotations=ToolAnnotations(...)` (`readOnlyHint`, `destructiveHint`, `openWorldHint`) so
   clients can tell a read from a destructive call.
6. Raise `PerplexityError(category, message)` for every anticipated failure. Anything else is
   masked to `internal_error`.
7. **Do not use `from __future__ import annotations` in a tool module**: FastMCP reads annotations
   at registration time and `Context` must be a real class there.
8. A tool that makes a costed upstream call records it: follow "How to record usage" below, in
   that order (a new Agent API tool calls `agent.run_costed`, which already is that order). A read-only tool (`perplexity_models`, `perplexity_usage`) opens
   `unit_of_work(engine, write=False)` and never creates a project.
9. Test it offline through `build_server` with a `MockTransport` client (see `tests/test_tool_errors.py`,
   `tests/test_projects_tool.py`). **Every tool schema costs context in every session.** Going from
   three tools to seven grew the `tools/list` response from 10564 to 39463 bytes (about 10.5 KB to
   about 39.5 KB, measured 2026-10-09 with `wc -c` on one `tools/list` POST; `design.md` "Risks"),
   most of it output-schema field descriptions. The design target is about nine tools in all, which
   leaves room for the Search, Embeddings and Decisions tools only if later epics stay lean: prefer
   one tool with an `action` argument over several, and trim descriptions before adding a tool.

### Error contract

Every tool failure is returned as an MCP tool error by `ErrorContractMiddleware`: text
`[category] message`, `structuredContent = {category, message}`, `_meta = {category}`. The
vocabulary is closed (`errors.ALL_CATEGORIES`, eleven values): `invalid_request`, `authentication`,
`forbidden`, `not_found`, `rate_limited`, `upstream_failure`, `network_timeout`,
`unexpected_response`, `confirmation_required`, `storage_busy`, `internal_error`. Mapping: a
`PerplexityError` keeps its category; a SQLite busy error is `storage_busy`; FastMCP argument
validation is `invalid_request`; an unknown tool is `not_found`; everything else, including a
plain `ToolError`, is `internal_error` with a fixed generic message while the real exception is
logged at ERROR (redacted). HTTP status maps by `errors.category_for_status`, never by the
API's error `type`. Upstream text is redacted on construction because it can echo a submitted key.
Adding a category means updating the spec, `errors.py`, the README table and the tests together.

### Storage and migrations

- One SQLite file, `perplexity.db`, in `PERPLEXITY_DATA_DIR` (default `~/.perplexity-pro/`, mode
  0700; the file 0600). WAL mode, `busy_timeout` and `foreign_keys=ON` are set on connect. The
  server never writes into the calling project's directory.
- Migrations are `migrations/versions/NNNN_slug.py` (four-digit sequence, no gaps, chained). Each
  **must** have a working `downgrade()`; a test enforces naming and reversibility.
- The runner (`storage/migrate.py`) uses a synchronous engine before the async one starts, under
  an exclusive `migrate.lock` file (60 s bounded wait), copies a database that has a recorded
  revision to `backup-<revision>.db` with SQLite's online backup API, then runs the upgrade inside
  one `BEGIN IMMEDIATE` transaction (transactional DDL: a failed migration rolls back). It refuses
  a database newer than the code. Restoring a backup is a manual procedure (README), not code.
- Project-scoped tables: give the table a column with a foreign key to `projects.id` declared
  `ON DELETE CASCADE`. `delete_project` finds such tables by introspection, so it needs no edit.
- **Retained tables** (records that must outlive their project; `usage_events` is the first):
  declare the key `ON DELETE SET NULL` (nullable column) AND add the table's own name column (such
  as `project_name`) holding the project name as written, because the reference is gone after
  deletion. `delete_project` detaches those rows with `UPDATE ... SET <col> = NULL` and reports
  them in `rows_retained`; it needs no edit either. Limits, each refused with a `StorageError`
  naming the table (never half handled, see `storage/projects.py:_scoped_tables`): no table may mix
  SET NULL and CASCADE keys to `projects`; no composite foreign key to `projects`; no `NOT NULL`
  column declared SET NULL. A table two hops away is handled by its own `ON DELETE` rule and is in
  neither count.
- Every stored record belongs to a project; `get_or_create_project` is the only resolver, and it is
  used only by actions that store something (`perplexity_ask`, `perplexity_research` and a chat
  `send` that starts a chat, through `run_costed`). Chat `list`/`read`/`delete`, a `send` with a
  `chat_id` and every `perplexity_jobs` action only look the project up (`find_project`): an absent
  one is `not_found` (empty for `list`), and they never create it.
- `chats` and `research_jobs` (migrations `0003`, `0004`; `chat_messages` hangs off `chats`) are
  ordinary project-scoped tables (`ON DELETE CASCADE`), so deleting a project removes them, while
  `usage_events` stays. A downgrade of either migration drops its rows (`backup-<rev>.db` has them).

### SQLAlchemy session convention (design D10)

The house convention proposed in `design.md` D10 and implemented in `storage/session.py`:

- **One `AsyncSession` per tool call**, obtained from `unit_of_work(engine, write=True)`. It is an
  `@asynccontextmanager` function (FastMCP would hand a bare async generator to the tool as an
  object). Never open a session any other way, and never share one across calls.
- **Commit when the block returns; roll back on any exception**, including `BaseException`, so a
  call that fails after writing leaves nothing behind (the "all-or-nothing" requirement).
- **Write units of work start `BEGIN IMMEDIATE`** so the write lock is taken up front and
  `busy_timeout` applies (a read-then-write transaction in WAL mode fails instantly with BUSY and
  ignores the timeout). Pass `write=False` for a read-only call.
- A lock held past the timeout surfaces as `PerplexityError("storage_busy", ...)`.
- **The cleanup survives cancellation.** `rollback()` and `close()` run as their own shielded task,
  because FastMCP and anyio cancel with a level-triggered scope that cuts a bare cleanup short and
  leaves the connection checked out (`tests/test_unit_of_work_cancel.py`). A write that must land
  after the provider has already acted (a job row, `cancel_requested_at`, the recorder) is shielded
  the same way by its caller.
- **Get-or-create is an upsert** (`INSERT ... ON CONFLICT DO NOTHING`, then select), so concurrent
  first creates cannot violate a unique constraint.
- `expire_on_commit=False`, so returned ORM objects stay readable after the block.

## How to record usage

Every costed upstream call (Agent, Search, Embeddings, Decisions) stores one `usage_events` row
through `usage.record_usage` (contract: `openspec/changes/archive/2026-10-09-py-usage-log/design.md`
D6 to D8). SQLite has one writer and a write `unit_of_work` holds its lock until it commits, so the
order matters:

1. `validate_project_name(project or DEFAULT_PROJECT)` (pure, no database).
2. Resolve the project with `get_or_create_project` in a short write unit that **commits before
   the call**. A project created here survives a later failure of the call (an empty project).
3. Make the upstream call holding **no write unit**. A write unit open across an LLM call blocks
   every other writer for its length.
4. `await record_usage(engine, tool=..., api=..., status=..., usage=body.get("usage"), model=...,
   preset=..., request_id=body.get("id"), project=name, latency_ms=..., secrets=(api_key,))`
   while holding no write unit on that engine. Inside the caller's open one it waits the busy
   timeout for its own caller's lock, fails and returns `False`, and the event is lost.
5. Run the tool's own write unit **last**, so its rollback on failure cannot remove the event.

For a failed call (a `PerplexityError`), record with `status=exc.category` and no usage, then
re-raise. A pure example of the whole pattern is `tests/usage_support.py:costed_call`.

**Production callers.** `record_usage` is called from exactly two places in `src/`, found with
`rg "record_usage\(" src/` (the definition in `usage.py` aside), and a new costed tool must not add
a third by inlining the sequence above:

- **`agent.run_costed`** (two `record_usage(` lines, the failure and the response). It does steps 1
  to 4 in that order: validate the project name, commit the project in a short write unit
  (`resolve_project=False` for a chat send that already found its project), the timed call with no
  write unit open, then record. `perplexity_ask`, `perplexity_chat` send and the
  `perplexity_research` submit call it, and each does its own write (a chat row, a job row) after it
  returns, which is step 5. **A new costed Agent tool calls `run_costed` instead of inlining the
  sequence.** A background submit records only a terminal body; a queued run is recorded later.
- **The observation core, `agent.observe_job_locked`** (called under the job's lock by
  `observe_job` and by `perplexity_jobs cancel`). It records a background run at its first terminal
  observation: under the job lock it re-reads the row, fetches, and if the run is terminal and no
  event for its response id exists yet (`_event_exists`: the unique index only covers `ok` events),
  calls `record_usage` with no write unit open, then updates the row in its own shielded unit. One
  observation is two units of work and no two jobs share one. A run nobody observes is never
  recorded; a project deleted with running jobs loses their spend (`running_jobs`).

- **Status.** For an Agent response call `agent_response_status(body)`: `"ok"` records it,
  `"unexpected_response"` records it with that status and whatever usage it reports, and `None`
  (queued or in progress, no usage yet) means **do not record**: an `ok` row for a pending response
  would take the dedupe key of the real terminal one. Never re-derive that rule.
- **Pass the raw mapping.** `usage` accepts a parsed `Usage`, the raw usage mapping or `None`; the
  recorder parses a mapping itself, inside its guarded block, with the parser registered in
  `_PARSERS` for `api`. A new API adds its parser there after probing the live response; an API
  with none stores the mapping with cost source `none`. Pass `body.get("usage")`, never
  `body["usage"]`. If the response carries no cost, build the usage with `computed_usage(cost,
  **facts)` from `pricing.py`, which stamps `PRICES_AS_OF`.
- **It never raises an error** (a cancellation is re-raised after the shielded write lands; it catches `Exception`, logs with secrets removed, returns `False`). `True`
  means stored. `False` also covers an unknown `api` or `status`, and a duplicate: one `ok` row per
  `(api, request_id)`, enforced by a partial unique index, so a retry of the same response is not
  counted twice. Errors have no such key and always store.
- **Cancellation.** The write is shielded, so a cancel arriving after the upstream call returns
  still lets the event land. A call cancelled before the response is not recorded and may still
  have been billed.
- **Redaction.** Pass the API key in `secrets`. Every text field and `usage_json` is redacted
  before storage (`redaction.redact_text`); the documented `pplx-embed-*` and `pplx-decider-*`
  model ids are exempt so they are stored as written. A project name is validated, never redacted.
- **Money** is integer nano-USD (10^-9 USD), never a float; a cost is `reported`, `computed` or
  `none` (unknown, stored as 0). `perplexity_usage` states the sum as a lower bound.

## Testing

- **Offline by default.** `tests/conftest.py` installs a socket guard that fails any connection to
  a non-loopback address. Opt out only with `@pytest.mark.allow_network` (live tests, the test that
  connects to the host's own address to prove a refusal, and the guard's own check in
  `tests/test_smoke.py`).
- **Fake the API with `httpx2.MockTransport`** injected into an `httpx2.AsyncClient` passed to
  `build_server`/`PerplexityClient`. `respx` and `pytest-httpx` do not intercept `httpx2`.
- **Fixtures** in `tests/fixtures/` are real, scrubbed API responses, each with a `.meta.json`
  (endpoint, capture date). Never hand-write one; build synthetic edge cases inline in the test.
  `tests/test_fixtures.py` scans them for key-shaped strings. Probe the real API before modeling it
  (`docs/lessons/docs-lie-probe-the-api-first.md`); re-record with
  `PERPLEXITY_API_KEY=... uv run pytest -m live tests/test_live_capture.py`.
- **`live` marker**: calls the real API, deselected by default (`addopts = -m 'not live'`), run
  with `-m live`. Never required for a commit.
- **`build` marker**: runs `uv build` (the hatchling build backend may need the network), deselected
  by default (`addopts = -m 'not live and not build'`), run with `-m build`; CI runs it as its own
  step after the main suite.
- Tests inject a dummy key through `make_settings`; the suite must pass with no
  `PERPLEXITY_API_KEY` in the environment. FastMCP deprecation warnings are errors.
- **Mutation-check rule** (`docs/lessons/cleanup-tests-must-fail-when-cleanup-is-removed.md`):
  after writing a test for shutdown, close, rollback or lock behavior, delete the code it protects
  once and confirm the test goes red. Assert on a side effect (a file written after the close, an
  intact backup), not on a log line that claims the work happened.
- Server tests start the real HTTP runner on an ephemeral port (`tests/server_support.py`:
  `free_port`, `serving`, `rpc`) or a subprocess (`tests/fixture_server.py`).

## Configuration and operations

- Environment variables, prefix `PERPLEXITY_` (table in `README.md`; defined once in
  `settings.py`): `API_KEY` (required), `HOST` (127.0.0.1), `PORT` (8102), `BASE_URL`, `DATA_DIR`,
  `LOG_LEVEL`, `CONNECT_TIMEOUT`, `READ_TIMEOUT`, `AGENT_READ_TIMEOUT` (120 s, a synchronous Agent run only), `MAX_ATTEMPTS`, `MAX_RETRY_WAIT`, `CATALOG_TTL`,
  `CATALOG_MAX_STALE`, `DB_BUSY_TIMEOUT`. No `.env` file is read. Never use the `FASTMCP_` prefix
  for our own settings (FastMCP reads it).
- **Never print, log, commit or paste the API key.** It is a `SecretStr`; logs go through the
  redacting handler to stderr only (stdout is the protocol in stdio mode).
- **Live server: pm2, app `mcp-perplexity-pro`, port 8102** (registered in `~/SERVER_PORTS.md`),
  health `GET http://127.0.0.1:8102/health`. Do not stop or restart it to test; start your own
  instance on an ephemeral port with a dummy key and a temp `PERPLEXITY_DATA_DIR`.
  `ecosystem.config.cjs` holds the real key and is gitignored; `ecosystem.example.cjs` is the
  key-free template (`kill_timeout: 15000`, which must exceed the server's 10 s shutdown bound;
  `tests/test_ecosystem_example.py` guards it). Never edit the real one in a commit.
- Graceful shutdown: SIGTERM/SIGINT (or stdin EOF in stdio) stops new calls, waits up to 10 s for
  running ones, closes the HTTP client and engine, exits 0.
- Non-loopback `PERPLEXITY_HOST` logs a warning: the endpoints are unauthenticated.

## Non-goals and retired code

- **No data import from 1.x.** The old `.perplexity/` project folders are not read.
- **The TypeScript sources and their packaging and container files are deleted** on the `python-rewrite` branch. Do not
  propose converting anything back or reviving the 1.x tool names. The Sonar models and
  `/chat/completions` endpoints are retired by Perplexity and must not be called.
- Not built yet: the Search, Embeddings and Decisions tools (the Agent tools exist and record
  their usage), streaming, auto-routing between depths or models and cost ceilings (there is none:
  `high` and `xhigh` exist only behind `perplexity_research` for that reason), pruning of chats,
  jobs or usage events, PyPI publishing (the package only has to build and run via `uvx --from .`).

## Workflow: where things live

- `.conductor/` is the pm conductor state (`state.json` is the state of record; `PROJECT.md` is
  generated, never hand-edit it). `openspec/` holds change records: `openspec/changes/<id>/`
  (`proposal.md`, `design.md`, `specs/*/spec.md`, `tasks.md`). The current change is
  `py-agent-api` (`py-foundation` and `py-usage-log` are archived). `docs/lessons/` holds process lessons
  with their enforcement points.
- Commits are conventional (`feat|fix|docs|test|chore(scope): subject`), one per task, with the
  task's `tasks.md` checkbox ticked in the same commit.

<!-- BEGIN pm-conductor rules (managed by pm — safe to delete this block) -->
## PM Conductor — operating rules

This repo is managed by the `pm` plugin. The conductor sits ABOVE OpenSpec and Superpowers.
Epics are **lane-agnostic** (openspec | superpowers | claude-code | decision | external);
OpenSpec is one lane. Stories come from each epic's source (OpenSpec `tasks.md`, a Superpowers
plan, or a manual list). Follow these rules:

1. **Detours** — when something blocks the active epic, CLASSIFY before fixing:
   - *Minimal* (small, self-contained, no design ambiguity): fix → test → commit → push,
     then run `/pm:detour --minimal "<what>"` so it is recorded in `.conductor/detours.log`.
     Then resume.
   - *Substantial* (own design / changes shared behavior / multi-step): run `/pm:detour`.
     It becomes its own epic in the appropriate lane (OpenSpec proposal, Superpowers plan,
     etc.). Register that epic FIRST, then PUSH the current one onto the detour stack with
     `push-detour <parent> --detour <new-id> --reason "<why>" (--reconcile | --no-reconcile)`.
     NEVER hand-edit `.conductor/state.json` to push or pop a frame. The verb IS the
     transition, and it is what supplies the validation, the write-conflict guard, the
     read-back verification and the Honcho line a hand-edit has none of. Exactly one of the
     two reconcile flags is REQUIRED and there is no default: whether the detour can
     invalidate the paused epic's plan is a judgment, and a default makes an absent decision
     look like a considered one. Say `--reconcile` unless you are certain the detour touches
     nothing the paused epic depends on.
2. **State of record is `.conductor/state.json`.** After any change to epics, status,
   priority, or the detour stack, re-render with `/pm:status`. Never hand-edit `PROJECT.md`.
3. **Resuming after a detour** — use `/pm:resume`, which pops the frame with
   `pop-detour [<paused-id>]` — again a verb, never a hand-edit. It removes the frame,
   resumes the epic and writes `reconcileNeeded` in the SAME write, which is what makes the
   obligation survive the frame's removal. If the popped frame had
   `reconcileOnResume`, run the reconcile gate (reconciler agent) BEFORE writing code,
   then write its verdict back durably with `record-reconcile <id> --detour <id>
   --verdict valid|invalidated [--amendments "<a>;<b>"]` — this attaches
   `{verdict, amendments, reconciledAt}` to the paused epic's link to the detour and
   clears `reconcileNeeded`, instead of the judgment only ever living in conversation.
4. **Honcho** — on every PUSH and POP, also write a one-line memory to Honcho
   ("paused X for Y" / "resumed X, reconciled vs Y") so the relationship survives outside
   this repo. `push-detour` prints the PUSH line for you and logs it to
   `.conductor/honcho-memories.log`; paste it into your Honcho tool call. `pop-detour` prints
   the POP line only when nothing needs reconciling — with a gate armed, "reconciled vs Y" is
   not yet true, so emit it with `honcho-memory pop <id> "<detour>; reconcile = …"` after the
   verdict. The engine formats and logs; it never calls Honcho itself.
5. **Keep `tasks.md` checkboxes truthful** — they are the source of truth for story progress.
6. **Roadmap as backlog** — work you intend to do but haven't proposed yet can be
   registered now with `/pm:epic add … --status planned` (any lane). Planned epics show
   as ordered backlog in `PROJECT.md` and a `planned: N` count in the briefing, without a
   "no change on disk" warning; `/pm:sync` flips an openspec planned epic to untriaged once
   its change is proposed. Have a roadmap doc? Read it in-session and load each item this way.
7. **Delegate discovery. If you do not already know the file path, do not go looking
   yourself.** A subagent's transcript never enters yours — only its final report does — so
   an open-ended read costs a conclusion instead of a transcript when it is delegated.
   "Where is X handled", "does a spec for this already exist", "what does this epic touch",
   "what did the last three changes here do": dispatch an `Explore` or `general-purpose`
   subagent and use what it concludes. Reserve an INLINE read for the narrow case where you
   already know the exact file and want one value out of it.
   This binds the ORCHESTRATING agent, which is the half that has no such rule: a dispatched
   child is already told to return a fixed report and not to narrate. It binds hardest across
   a hierarchy run or a multi-epic backlog, where your context survives many epics and is
   therefore the scarce resource — discovery you perform inline is paid for once per epic and
   never reclaimed.
   DELEGATING NEVER WEAKENS A FULL-READ REQUIREMENT. Where this instruction demands the whole
   document — the epic-level-autonomy preflight scan, and re-reading an epic's source before
   it becomes the work — the subagent reads the whole document and returns the finding. What
   is forbidden is substituting a keyword grep for a full read, and that is forbidden
   whoever performs it.

## Getting help with pm — two channels, and which one can lie

**The INSTALLED engine is the authority on what it accepts.** `node "$ENGINE" <verb> --help`
(resolve `$ENGINE` the way pm's own command docs do) prints that verb's real flags, projected
from its own registry — version-exact by construction. Use it before reading engine source.

**For procedure and rationale:** https://pm-plugin.dev/llms.txt indexes the docs (entries are
already markdown); a free, no-auth MCP at https://pm-plugin.dev/mcp answers in one call.

**The site documents the LATEST release, which may be newer than the pm running here.** A flag
it shows that your engine refuses is a version gap, not a bug — `/pm:changelog` says which.

## The gate procedure — required task items

Every item below is a NUMBERED REQUIRED TASK ITEM in the change's own task list, carried
into both gates. They are not review guidance and must not be restated as prose bullets:
measured across one audited repository, a rule carried by a mandatory task section reached
14/14 subsequent changes, while the same rule written as a prose bullet reached 3/15.

1. **Call-site completeness sweep.** For every rule, guard or invariant this change introduces
   or modifies, enumerate ALL call sites of the thing being guarded — derived mechanically
   (`rg` for the callers), never a list typed from memory, which goes stale the moment a
   caller is added. Then state where the rule holds and where it does not, and
   justify each omission. A guard added at one call site while an identical sibling site is
   left untouched is a FINDING, not a detail: raise it even though the unedited site never
   appears in the diff. Both gates are diff-scoped and structurally cannot see an edit that
   is absent from a file the diff never touched — the dominant defect class in this
   repository's own audit, ~38 instances in one shard.
   A DATA reference is a call site too: for every field the change adds that holds another
   record's id, enumerate the places that write it, read it and REMOVE it. A deletion path
   that strips one holder and not its siblings leaves a dangling reference — the record
   rendering a pointer to something that no longer exists — and it is invisible to both
   gates for the same diff-scoped reason.
   AN OPERATION HAS AN INVERSE, and the sweep above cannot reach it. For every operation
   this change adds or modifies, enumerate that inverse — set against unset, add against
   remove, append against replace, enable against disable, grant against revoke — then
   name and justify each inverse that is not shipped, exactly as an unguarded call site
   must be. An operation shipped without its inverse, and not justified, is a FINDING.
   The reason the sweep cannot reach this class is mechanical rather than a matter of
   diligence: enumerating the callers of a thing that is written never leads to the
   question of whether it can be unwritten. Measured here, six instances shipped past both
   gates while the call-site obligation was already in force, and the most consequential
   is a safety surface — pre-authorization grants accumulate with no revoke, so turning
   autonomy off leaves every prior grant intact and turning it back on silently restores
   all of them.
2. **Verify against the commit, not the working tree.** The commit is the unit of verification.
   Reading a file in the working tree is NOT verification. For every task, run
   `git show --stat <that task's sha>` and assert that
   every file the task claims to change appears in THAT commit. A task whose claimed file is
   absent from its commit FAILS, even though the working tree holds the intended edit, the
   suite passes and both gates are green. Audited here: two commits each claimed to remove a
   file's code and neither staged it, because a `git add` with an explicit path list aborted
   on an already-removed path — all four verification layers were reading the working tree,
   so nothing caught it, and it recurred after being written down in a commit message in the
   same epic.
3. **Declare lifecycle bookkeeping.** A task that is bookkeeping about the change's own
   lifecycle rather than its work — above all the task that ARCHIVES THE CHANGE ITSELF, which
   always qualifies — carries the literal marker `<!-- pm:lifecycle -->` ON THE TASK LINE.
   The engine infers this from nothing else: not the wording, not the commands the text
   names, not the position in the file. Mark it at the moment the task source is AUTHORED
   OR AMENDED — a source written before this capability existed gets the marker the first
   time you touch it, or its archive task counts as outstanding work forever.
   The marker is pm's alone and it COLLIDES with an upstream lint: `openspec validate
   --archived` knows nothing about it, counts raw checkboxes, and therefore FAILS every
   correctly archived pm change — reporting `1 incomplete task` against the same file pm
   reports complete with `· N lifecycle`. Its own help text offers it for pre-commit
   linting; do NOT wire it into a pm-managed repo. Nothing clears that failure: ticking the
   archive task would be a false record and dropping the marker would break pm's own archive
   gate. Ignoring a marked line upstream is the clean fix and it is not pm's to make.
4. **Attribute every commit to its epic.** At the moment each commit is made, record it:
   `update-epic <id> --attribute-commit <sha>`. The engine infers attribution from NOTHING —
   not the files a commit touches, not an epic id in a message — so an unrecorded commit is
   a commit the epic's Gate 2 cannot be checked against. The per-task conventional commit of
   an OpenSpec apply loop always qualifies. Work already in flight is covered too, but ONLY
   BEFORE the first attribution: catch up in the order the commits landed, then keep
   attributing forward. The array is append-only — the engine neither reorders nor
   de-duplicates it — so catching up AFTER attributing forward leaves an ancestor as the
   last entry, and the LAST entry is the endpoint a recorded Gate 2 `headSha` is compared
   against. If forward attribution has already begun, attribute forward only and say so;
   a wrong endpoint reads as a stale verdict and refuses the archive.
   ONE EXCLUSION, and it is not a judgment call: the commit that moves
   `openspec/changes/<id>/` under `archive/`, and any commit that only relocates or deletes a
   change's artifacts rather than implementing its work, is lifecycle bookkeeping and
   MUST NOT be attributed. That move lands after the reviewed range by construction, so
   attributing it
   makes the epic's own Gate 2 stale at the instant the archive gate reads it.
5. **Review a release's specs against each other.** Gate 1 and Gate 2 each take ONE CHANGE
   as their unit, so nothing above them asks whether a release's specs AGREE. Before
   `/opsx:apply` on any release holding two or more spec files — counted FLAT across its
   member changes, so one change carrying six specs qualifies — and again after any round
   of concurrent amendment, dispatch FRESH-CONTEXT reviewers at the release's whole spec
   set (one under `standard`, two with different lenses under `thorough`) and ask the six
   questions: contradiction, double ownership, unmeetable requirements, gaps against the
   proposal's Resolves list, vocabulary forks, and shared chokepoints. Split every finding
   into BLOCKS and POLISH, fix the BLOCKS, decline most POLISH and say why — a review of a
   large document always returns something, so "no findings" is not a stopping condition.
   A contradiction is never POLISH. Then record the verdict:
   `record-cross-spec-review <releaseId> --verdict pass|fail --reviewer "<identity>"`.
   The engine enumerates the spec set from disk and hashes it, so a spec ADDED to the
   release afterwards — or a reviewed spec amended — marks the verdict stale on every
   surface; a set you assert instead would go stale in exactly the way this gate exists to
   catch. Measured here: this pass returned 5 Critical and 10 Important against six specs
   that had each passed `openspec validate --strict` and would each have passed Gate 1
   alone, including a flagship scenario that was unreachable.
6. **End work by recording a disposition.** An epic, a story, a deferral or a release
   exclusion ENDS by recording a terminal disposition carrying its required reason, and
   never by removing the record. The archive verb takes TWO halves in ONE invocation — the
   disposition AND a deferral assertion — because the gate refuses either half alone:
   `update-epic <id> --status archived --outcome delivered|killed|superseded|abandoned|declined|unreconstructable --reason "<why>" --no-deferrals`
   (every outcome except `delivered` requires the reason). `--no-deferrals` is the explicit
   "there are none" and is a claim, not a default — swap it for `--deferral
   "<epicId>:<artifact section>"` where work is now held by a registered epic, or
   `--declined-deferral "<what>:<why not>"` where you are deliberately not doing it; both
   repeat, and the engine will not read your artifacts to guess.
   Deletion removes the record of projected work, which is
   precisely what a disposition exists to preserve. `remove-epic` stays available and
   ungated for what it is for: an epic registered in error, a duplicate, a mistake made a
   minute ago — where there is no disposition to record because there was no work.
7. **Route what the work taught you.** A change teaches three kinds of thing and each has a
   different destination. Route them BEFORE the change closes, while the evidence is still
   recoverable. Nothing above this asks, so silence here reads as "nothing was learned"
   rather than "nobody looked", and the two are indistinguishable afterwards.
   A PRACTICE, GATE OR DISCIPLINE you adopted to get this change done: register it as an
   epic, and file it with the tracker as well when it belongs to a product other people
   use. The evidence goes with it — what went wrong that made the practice necessary,
   with numbers. That evidence is the strongest part of the eventual spec and it is
   unrecoverable later; a practice registered without it reads as a preference.
   FRICTION IN THE TOOLING that you routed around: file it — `/pm:feedback [bug|feature]
   "<summary>"` for pm itself, and wherever it is tracked for anything else. THIS IS THE
   DIRECTION THAT GETS MISSED, and the reason is mechanical: a workaround produces working
   output, so nothing looks broken and nothing prompts. Hand-editing a file a tool owns
   because no verb exists for it, a command the tool EMITTED that did not run as written,
   a convention you invented that the tool should have supplied, anything you did twice by
   hand that it could have done once — each of those is a filing, not a footnote. Measured:
   two sessions hit one broken recipe in an afternoon, each invented a workaround, neither
   reported it until asked.
   A PROCESS FAILURE — how we work, rather than what the tool should do: a lesson file in
   `docs/lessons/`, carrying its `trigger` written as the situation BEFORE the mistake, a
   concrete `cost`, and `enforced_in` naming where its rule actually binds. Give it a
   `detect:` matcher only where the situation is recognisable with near-certainty — the
   `lesson-advice` hook fires on that matcher before the next mistake, and a hook that is
   wrong 7 times in 8 trains everyone to ignore the one time it is right, so a lesson that
   cannot be matched precisely stays retrieval-only.
   Name which of the three it is out loud. A process lesson filed as a feature request
   never gets built, and a product gap written down as a lesson never gets fixed.

## Intake — triage an ask against the whole backlog BEFORE registering it

The ask is the ONLY moment the whole backlog is cheap to consider: after registration nothing
ever re-reads it as a set, so an ask that duplicates existing work in another shape becomes a
permanent second epic. The dedup that already exists is IDENTITY-based — same id, or the same
`externalUrl` — which catches a re-run of sync and nothing else. Measured in this plugin's own
repository: four live pairs are one change registered twice under different lanes and
different names, and identity dedup found none of them.

1. **Get the candidate set mechanically.** Before any `add-epic`, run
   `/pm:triage "<the ask, in its own words>"`. It returns the existing epics that share
   distinctive vocabulary with the ask (each with the shared tokens that put it there), the
   lane this repo's routing picks, and the backlog's current shape. It returns
   `verdict: null` and that is not a placeholder: the engine computes what is WORTH READING
   and never decides. Nothing about a lexical overlap is a claim that two asks are the same.
2. **READ the candidates — do not skim the scores.** Open each one that could plausibly be
   the same work. A high score with unrelated intent is a miss; a low score on an epic whose
   description turns out to cover the ask is a hit. This is the judgment the surface exists
   to make cheap, and it is yours.
3. **Record the relationship you found**, rather than leaving it in the conversation:
   `add-epic … --link "relates-to:<id>:<why>"` where the two asks inform each other;
   `--link "supersedes:<id>:<why>"` where this ask REPLACES an existing epic — then end the
   superseded one with its own disposition (`--outcome superseded --reason "<what replaced
   it>"`), because a consolidation that leaves both epics open has consolidated nothing.
   A candidate `triage` marks `superseded: true` is already dead — do not consolidate into it.
4. **Decide the lane; do not inherit it.** `triage` already ran `suggest-lane` for you and
   its answer reads THE ASK — the words, the size, this repo's `laneRouting` overrides — and
   nothing else. It cannot ask what a person would ask, whether this work SERVES something
   already committed to, because pm holds no milestone or product context to weigh and the
   engine will not invent one. The suggestion is an input; the lane is your call.
   THE TIE-BREAK IS ASYMMETRIC, and it is not a matter of taste. `claude-code` means no spec,
   no plan, no gate and no stories — right for a genuine sub-2-hour tweak, and the reason a
   misrouted epic leaves no record of what it was FOR. Over-processing costs hours;
   under-processing costs the record permanently, and nothing later can reconstruct it. So an
   unresolved routing question resolves AWAY from `claude-code`, never into it.
   Whenever you register in a lane other than the one routing suggested, say why on the epic:
   `update-epic <id> --notes "lane: <chosen> not <routed> — <why>"`. The tracker-sync
   procedures below already demand that line; it binds every path that registers an epic,
   this one included. Measured in pm's OWN repository, not necessarily yours: 83% of epics sat
   in `claude-code`, 51 of them already archived, none carrying an artifact link.
5. **Say no out loud when the answer is no.** Not every ask should be taken on, and declining
   by never registering it destroys the record that anybody considered it. Register it, then
   `update-epic <id> --status archived --outcome declined --reason "<why not>" --no-deferrals`.
   Two commands, deliberately: creating an epic directly at `archived` stamps an engine record
   carrying no reason, which is the silence this step removes.

**This is not a substitute for the identity dedup in the sync procedures below, and they are
not a substitute for it.** A URL match answers "have I already mirrored THIS item"; triage
answers "is this ask already in the backlog under another name". Run both.

## Reporting — pm owns what is recorded and what is said; you own how you say it

This section governs how you REPORT. It never governs what the sections above instruct you to
DO: a brevity contract shortens prose, it does not authorise skipping a required task item, a
gate, or a recorded disposition.

1. **A recorded fact is not output, and no contract shortens it.** `--outcome` and its
   `--reason`, `--no-deferrals` or the deferrals it stands in for, a gate verdict,
   `--attribute-commit`, `--notify`, `record-reconcile`, `record-cross-spec-review` — these
   are WRITES to `.conductor/state.json`, not sentences. Applying a communication preference
   to one is data loss, not brevity.
2. **A report another AGENT reads back is a wire format and does not bend.** The
   `hierarchy-child-executor`'s `STATUS/DONE/DECISIONS/CONCERNS` block, the
   `merge-conflict-resolver`'s, and the `reconciler`'s `VERDICT/AMENDMENTS/NOTES`: the
   orchestrator branches on `STATUS`, and `VERDICT`'s value space is enforced by
   `record-reconcile` one hop later. Keep those field names and that order exactly. The PROSE
   INSIDE a field is ordinary writing and follows item 3 like anything else.
3. **Everything a HUMAN reads follows the user's contract, not pm's.** The consolidated
   end-of-hierarchy report, the end-of-epic autonomy report, the preflight question batch, a
   gate summary, `/pm:status` narration, `/pm:next`'s recommendation. If the user
   has an output style, or a communication contract in their CLAUDE.md, render pm's
   human-facing output in THAT shape. pm's headings are a DEFAULT for a user who has
   configured none — not a house style that outranks one. Two competing formats in one
   session is the defect.
4. **Map the content into their shape; never drop it to fit.** Reshaping is always allowed;
   omitting is never. Where the user's shape has no slot for something pm requires — the
   `notifications[]` read-back, the explicit "are you OK with these?" checkpoint, the
   deferral list, a blocked child, a `CONCERNS` line worth flagging — ADD a slot rather than
   drop the element. Silently deleting an obligation to fit a terse contract is the same
   failure as imposing pm's format over theirs, pointed the other way.
5. **CLAUDE.md is the only channel that reaches a subagent.** A subagent inherits every level
   of the CLAUDE.md hierarchy the main conversation loads, `~/.claude/CLAUDE.md` included; an
   OUTPUT STYLE applies to the main conversation ONLY and does not reach one. So when you
   dispatch a `hierarchy-child-executor` or the `reconciler` and the user's contract lives
   only in an output style, carry it into the dispatch prompt yourself — otherwise the child
   cannot honour a preference it was never given.

## Epic-level autonomy

An epic's `autonomy` block (`.conductor/state.json`) can grant it broad execution trust —
`level: "off"` by default (today's behavior, unchanged). Setting `level: "autonomous"`
removes the need to ask before each phase transition, but NEVER removes a genuine safety stop.
This is development-time only — it never covers actions with irreversible EXTERNAL side
effects (sending email/Slack, deploying to production, third-party API calls, pushing to a
shared branch); those are out of scope regardless of autonomy level.

1. **Preflight before flipping the switch** — see the `conductor` skill's
   "Epic-level autonomy — the preflight scan" section for the full process. In short: read
   the epic's full source, produce a short batch of destructive-risk-points +
   genuine-unknowns questions, get the user's answers, THEN record them:
   `set-autonomy <id> --preauthorize "<action>:<reason>"` / `--context "<note>"`, and only
   then `set-autonomy <id> --level autonomous`. For routine, repeated categories of action
   instead of enumerating each one, use the shorthand
   `--preauthorize "category:<filesystem|network|schema|external-api>:<reason>"` — see the
   `conductor` skill's "Epic-level autonomy" section for the exact keyword heuristic each
   category matches at decision-rule time.
2. **Execution-time decision rule** — check every destructive action against these, in
   order, before treating it as a stop:
   a. Already pre-authorized in the preflight — either an exact `action` match or the
      action falls under a granted `category` (per the category heuristic)? → proceed,
      record via `--notify`.
   b. No backup/restore path exists? → STOP regardless of autonomy level.
   c. Destructive but restorable (backed up first)? → WARN — `--notify` it immediately, proceed.
   d. No context to act on? → STOP — a real gap, not a false stall.
   e. Consequential and not yet notified? → `--notify` it immediately, then proceed.
3. **Notify incrementally, not at the end** — `--notify` writes durably to `state.json`'s
   `notifications[]` the moment a WARN-class (c) or consequential (e) decision is made. Do this
   AS EACH DECISION HAPPENS, not batched — a session can be compacted or interrupted mid-epic,
   and anything not yet `--notify`'d is lost when that happens.
4. **End-of-epic report** — on completion, read back the accumulated `notifications[]` and
   report what was asked, what was done, and the decisions made in the user's absence (drawn
   from that log, not from memory), with an explicit "are you OK with these?" checkpoint, THEN
   run tests. Leave room to iterate — including rewriting code — if the user is not satisfied.

## Review mode

Review intensity is a bounded dial, not a free-form call each time — set via
`set-review-mode --mode <off|standard|thorough>` (default: `standard` if never set).

| Mode | Reviewer budget | Trigger |
|------|-----------------|---------|
| `off` | none — self-review only | tiny, low-risk, single-file claude-code tweaks |
| `standard` | one fresh-context reviewer per gate | the default: OpenSpec Gate 1/Gate 2, a Superpowers task review |
| `thorough` | two independent fresh-context reviewers per gate; adjudicate any disagreement yourself | schema/migration changes, security-sensitive work, or anything explicitly flagged high-stakes |

Current mode: **standard**.

## Feedback — don't let friction stay silent

If you hit a bug, a missing CLI verb, an unexpected limitation, or repeated friction
working with this plugin — in this repo or any repo using it — don't just work around it
and move on. File it: `/pm:feedback [bug|feature] "<summary>"` against `cfdude/pm`, or ask
the user "want me to file this as feedback?" if you're not sure it's worth it. The failure
mode this guards against is silent: hand-editing `.conductor/state.json` to flip a story's
`done` flag (no CLI verb exists for it) recurred across several separate sessions before
anyone reported it, even though `/pm:feedback` existed the whole time. A filed issue is
cheap; an unreported recurring papercut is not — silent pain is where a product fails its
users.

## Re-read the source before an epic becomes the work

An epic becoming active is the moment specs or a plan get drawn for it. Before that, re-read
what it is FOR. Which source depends on provenance, never on any tracker's direction:
- The epic has an `externalId` → re-read the LINKED ITEM (body, comments, labels, state), then
  record what you found: `record-tracker-refresh <id> --verdict unchanged|material-change
  --external-updated-at <iso> [--summary "<what changed>"]`. The timestamp is the tracker's
  own, never a local clock reading, and recording it clears the obligation.
- The epic has NO `externalId` → re-read its local source: its plan document, or its OpenSpec
  proposal plus its tasks. This one is instruction only — nothing is recorded in state for it,
  and `record-tracker-refresh` refuses such an epic by name rather than accepting a verdict
  about a linked item that does not exist.
An outward-mirrored epic owes the same look as an inward-born one: a linked item accumulates
third-party context regardless of which way it was born. Origin decides only whose ask wins
when the item and a local spec disagree.
<!-- END pm-conductor rules -->

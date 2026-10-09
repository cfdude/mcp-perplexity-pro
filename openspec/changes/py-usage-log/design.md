# Design

## Context

See `proposal.md` for motivation and `specs/` for requirements. State that shapes the approach:

- Foundation (`py-foundation`, archived 2026-10-09) left a `projects` table, a per-call unit of work (`storage/session.py: unit_of_work`, commit on return, rollback on any exception, `BEGIN IMMEDIATE` for writes), the shared get-or-create project operation, and `perplexity_projects delete`. Domain tables "arrive with the epics that own them"; this is the first.
- `delete_project` (`storage/projects.py`) finds project-scoped tables by introspection and runs `DELETE FROM <table> WHERE <col> = :id` on every table with a foreign key to `projects.id`. A new table with such a key would therefore have its rows deleted with the project, which is the opposite of what spend history needs.
- The only recorded usage shape is the Agent API's (`tests/fixtures/agent_fast.json`, `agent_background_poll.json`, observed 2026-10-09; see "Observed shapes" below). Search, Decisions and Embeddings responses have no fixtures, so their `usage`/cost shape is unverified.
- No existing tool makes a costed upstream call. `perplexity_models` calls the free `GET /v1/models`. The recorder therefore has no production caller until `py-agent-api` lands; a test-only tool (the foundation's pattern) is its caller here.
- Money precedent: the API returns costs as JSON floats in USD (`0.00021`, `0.00125`), and `perplexity_models` already shows prices as floats because those are a catalog, not an accumulating ledger.

## Goals / Non-Goals

**Goals:**
- One durable event per costed upstream call that returns or fails with a categorized error (best effort, see D6), successes and failures, with the full reported field set (it is irreversible accumulation data, so nothing visible in the payload may be dropped).
- Exact money: sums over thousands of calls equal the sum of the parts to the last unit.
- A recorder small enough that four later epics call it identically, and that cannot hurt the call it observes.
- A spend report that is honest about what it does not know (unpriced calls, computed costs).

**Non-Goals:**
- **Retention.** No pruning, archiving, export or size cap in this change. Growth is bounded by the call rate: the usage object of the Agent fixture is 501 bytes as compact JSON, so a row is dominated by that plus a few hundred bytes of columns (an estimate, to be measured in task 1.4 rather than asserted). Revisit when a real database shows a size problem; a future change can add a `--prune-before` style tool without schema change because `created_at` is indexed.
- Wiring any production tool (each later epic does, as part of its own change).
- Budgets, alerts, spend limits, currency conversion.
- Parsers for Search, Decisions and Embeddings responses (probe first; see D9).
- A switch to turn recording off (D12).

## Decisions

**D1. One table, `usage_events`, migration `0002_usage_events.py`.** Layout (every column nullable unless marked):

| Group | Columns |
|---|---|
| Identity | `id` (PK), `created_at` (UTC, NOT NULL, set by the recorder with microseconds), `tool` (NOT NULL), `api` (NOT NULL: `agent`, `search`, `embeddings`, `decisions`), `status` (NOT NULL: `ok` or an error category), `latency_ms` |
| Model | `model` (resolved), `preset` (requested) |
| Upstream id | `request_id` |
| Project | `project_id` (FK `projects.id`, `ON DELETE SET NULL`), `project_name` |
| Tokens | `input_tokens`, `output_tokens`, `total_tokens`, `cached_tokens`, `cache_creation_tokens`, `cache_read_tokens`, `reasoning_tokens` |
| Cost | `cost_nano_usd` (NOT NULL, default 0), `cost_source` (NOT NULL: `reported`, `computed`, `none`), `currency` (NOT NULL, default `USD`), `input_cost_nano`, `output_cost_nano`, `cache_read_cost_nano`, `cache_creation_cost_nano`, `tool_calls_cost_nano`, `price_table` (date of the constants, `computed` only) |
| Detail | `tool_calls_json` (normalized `{"search_web": {"invocations": 1, "cost_nano": 1000000}}`), `usage_json` (the `usage` object, sanitized and bounded per D6) |

Evidence for the columns: `agent_fast.json` `usage` carries `input_tokens`, `output_tokens`, `total_tokens`, `input_tokens_details.{cache_creation_input_tokens, cache_read_input_tokens, cached_tokens}`, `output_tokens_details.reasoning_tokens`, `tool_calls_details.<tool>.{cost_usd, invocation}` and `cost.{currency, input_cost, output_cost, cache_read_cost, cache_creation_cost (only when cache was written; absent in the poll fixture), tool_calls_cost, tool_calls_cost_details, total_cost}`. Fields absent in a response are NULL, never 0 (`cache_creation_cost` is the fixture-proven case).
Terminology: "tool" in `tool` is the MCP tool the client called; "upstream tool" (`search_web`) is what the Agent ran inside one call. `tool_calls_json` holds the upstream tools because their set is open (docs list `web_search`, `image_search`, `fetch_url`, `people_search`, `finance_search`, `sandbox`; only `search_web` has been observed), so it cannot be fixed columns.
Indexes: `created_at` and `project_name` (the report's filters), plus the dedupe index in D8. No `CHECK` on `api` or `status`: the recorder validates both against closed sets (`api` against its four values, `status` against `{"ok"} | errors.ALL_CATEGORIES`, the eleven-value error vocabulary), so a later category needs no migration but a typo stores nothing.
*Alternative:* a child table of upstream-tool rows. Rejected: JSON is enough for the one consumer (reports read `tool_calls_json` via SQLite's JSON functions if ever needed) and one more table is one more delete-semantics decision.
*Alternative:* only typed columns, no raw JSON. Rejected: a field the API adds tomorrow would be lost forever from rows already written; that is the irreversibility the foundation's Gate 1 rule exists for.

**D2. Money is an integer count of nano-USD (10^-9 USD).** Evidence: reported costs in the fixtures have up to five decimals (`0.00021`, `0.00002`), and every documented price converts to a whole number of nano-USD per unit: `$0.004` per million tokens is 4 nano-USD per token, `$0.02` is 20, `$5` per 1,000 requests is 5,000,000 per request. Micro-USD would make the cheapest Embeddings token 0.004 micro-USD, not an integer, forcing rounding on every computed event; nano-USD keeps every computed cost exact. SQLite `INTEGER` is 64-bit (about 9.2 billion USD); the per-cost cap above keeps every stored value and any plausible sum inside it. Conversion from a reported value goes through `Decimal` of the JSON text (`Decimal(repr(value))`, never `value * 1e9` on a binary float) and rounds half up; `0.00021` becomes `210000`. A JSON bool, NaN, infinity, negative or non-number is "unusable" and recorded as cost 0 with source `none` plus a log line (the stored `usage_json` still holds it, subject to D6 sanitizing). **`to_nano` is total and bounded:** `Decimal.quantize` raises `InvalidOperation` for large magnitudes (e.g. `1e30` exceeds the context precision) and a value above SQLite's signed 64-bit range would raise on insert and lose the whole event, so `InvalidOperation` or any result above `MAX_COST_NANO = 10**15` (1,000,000 USD for one cost: far above any single Perplexity call, and 10^15 keeps `SUM` over about 9,200 capped rows inside 2^63) is unusable exactly like a negative one. Token counts get the same treatment: a count that is not a plain `int` (bool excluded), negative, or above `MAX_TOKENS = 10**12` (a trillion tokens in one call, five orders above any context window) becomes unknown (NULL) plus a log line. Tests: `1e30` and `9.3e9` USD (which is 9.3e18 nano and overflows 64 bits). A currency other than `USD` is treated the same way: no conversion is attempted and mixing currencies into a USD total would be wrong. `format_usd(nano) -> str` produces an exact decimal string, trimming trailing zeros (`1230000` is `"0.00123"`, `0` is `"0"`).
*Alternative:* store floats. Rejected: a sum of floats is not the sum of its rows' printed values, and the report promises exact totals.
*Alternative:* `Decimal` columns. Rejected: SQLite has no decimal type; it would store text or float and lose exact `SUM`.

**D3. Cost source is a three-valued column, `none` being an addition.** The brief names `reported` and `computed`. A failed call and a call whose model has no documented price have neither a reported nor a derivable cost, and labelling their 0 as either would claim a measurement that was never made. `none` marks "0 because unknown", and the report counts successful calls with source `none` so a total is visibly a lower bound. A reported 0 (a free response) stays `reported`. Caveat: a call that failed after the provider began work (a read timeout) may still have been billed; we cannot know, which is exactly what `none` says.

**D4. Pricing constants (`pricing.py`), verified 2026-10-09 against `https://docs.perplexity.ai/docs/getting-started/pricing.md`** (fetched with `curl -sL`; the page's tables, not its calculator script, were the reference, and the two agreed):

| Item | Documented price | Stored constant |
|---|---|---|
| Search API, standard | $5.00 per 1,000 requests | 5,000,000 nano per request |
| Search API, Fast Search (`search_type: "fast"`) | $1.00 per 1,000 requests | 1,000,000 |
| Decisions `pplx-decider-v1.1-27b` and `pplx-decider-v1-27b` | $0.02 per 1M input tokens, output free, no per-request fee | 20 nano per input token |
| Embeddings `pplx-embed-v1-0.6b` / `-4b` | $0.004 / $0.03 per 1M tokens | 4 / 30 nano per token |
| Embeddings `pplx-embed-context-v1-0.6b` / `-4b` | $0.008 / $0.05 per 1M tokens | 8 / 50 nano per token |
| Agent `web_search` standard / Fast Search | $0.0025 / $0.001 per invocation | 2,500,000 / 1,000,000 |
| Agent `fetch_url` | $0.0005 per invocation | 500,000 |
| Agent `people_search`, `finance_search` | $0.005 per invocation each | 5,000,000 |
| Agent `image_search` | $0.0025 per successful invocation (not in the brief; on the page) | 2,500,000 |
| Agent `sandbox` | $0.03 per session (20-minute billing window); searches made inside it $0.0025 each | 30,000,000 / 2,500,000 |

Constants carry `PRICES_AS_OF = "2026-10-09"` and `PRICES_SOURCE` (the URL). Every price came from the page; nothing is inferred. **Unverified:** (a) the key under which the Agent's `usage.tool_calls_details` reports each upstream tool: only `search_web` was observed (it appeared for the `fast` preset at $0.001, so the key does not distinguish standard from fast search), the docs name the tool `web_search`; `pricing.py` therefore keys by documented name and carries the one observed alias, and any other alias is a task for `py-agent-api` to confirm against a live run; (b) whether Search/Decisions/Embeddings responses report a cost at all (no fixtures). Prices apply only when the API reports no cost (D3); Agent token prices are not constants here because the response reports cost and the live catalog (`perplexity_models`) carries per-model token prices.

**D5. Spend history survives project deletion: `project_id` is `ON DELETE SET NULL`, `project_name` is denormalized.** The event keeps the name as written at the time, so history is reportable by name after the project row is gone, and a project later recreated under the same name gets a new id and does not silently adopt old events (the reporting spec groups by name, so the two still line up in reports by design). Reports group and filter on `project_name`, never on `project_id`. *Evidence of the problem:* `storage/projects.py` `_scoped_tables()` returns every table with a foreign key to `projects.id`, and `delete_project()` deletes from each, so a plain FK would delete the ledger with the project.
*The convention for later tables* (specified in `local-storage` "Retained records"): a foreign key to `projects.id` declared `ON DELETE SET NULL` makes the table retained; `ON DELETE CASCADE` or no action keeps today's behavior (cleared and counted). `delete_project` reads each table's delete rule, deletes from ordinary tables as before, and for retained tables runs `UPDATE <table> SET <col> = NULL WHERE <col> = :id` explicitly and counts the rows, so the count does not depend on the database's own cascade and the "detached" number exists; the SQLite foreign-key action would do the same on commit anyway. **Verified 2026-10-09:** SQLAlchemy's `Inspector.get_foreign_keys()` returns `options: {}` on SQLite, with no `ondelete` (checked on SET NULL, CASCADE and plain keys), so the introspection moves to `PRAGMA foreign_key_list(<table>)`, whose `on_delete` column returns `SET NULL`, `CASCADE` or `NO ACTION`. The PRAGMA's `to` column is `None` when the key is declared `REFERENCES projects` without naming a column; SQLite then means the parent's primary key, so the parser maps `to = None` to the referenced table's primary key (`id`) before comparing. A test declares a key both ways. This introspection change lands before the `usage_events` migration (tasks 1.2 before 1.3), so no commit has `usage_events` present while `delete_project` still deletes its rows. A retained table must also have a name column; the migration test asserts that the delete rule and the denormalized name are both present, which is the only enforcement a convention can have.
*Alternative:* no foreign key, only `project_name`. Rejected: loses referential integrity for live projects and does not exercise a convention the next retained table (chats history, decisions) will want; costs one PRAGMA read.
*Alternative:* a hard-coded list of retained tables in `projects.py`. Rejected: it is the registry the foundation deliberately avoided ("needs no change when a table is added").
Spec consequences (MODIFIED in `specs/local-storage`): "Project resolution" ("every stored record SHALL belong to a named project", lines 61-62 of `openspec/specs/local-storage/spec.md`) is false for events without a project; "Project management tool" (line 87, "removes the project and all its records") would delete spend history and has no detached count; "All-or-nothing tool calls" (line 113, "one unit of work") is contradicted by D6 and is restated to also forbid a write unit open across an upstream call. Ownership: `local-storage` owns the detach-on-delete behaviour ("Retained records", "Deleting a project keeps retained records"); `usage-recording` only requires that events stay reportable by name afterwards. Added: "Retained records" and "Deleting a project keeps retained records". Unchanged and still true: "Project names", "Project deletion outcomes", "Single local database", "Versioned migrations" (0002 is reversible and takes the pre-migration backup), "Concurrent calls".
`perplexity_projects` result gains `rows_retained`; its tool description changes from "everything stored in it" to say spend history is kept. The new field is additive, so a client that ignores it keeps working.

**D6. The recorder is best-effort, post-call and isolated.** `record_usage` runs after the upstream call returns or fails, in its own `unit_of_work(engine)`, so a rollback of the tool's own writes (spec "All-or-nothing") cannot remove the event and a recording failure cannot roll back the tool's writes. It catches `Exception` (not `BaseException`), logs through the existing redacting logger (`logger.warning`, message and `exc_info`, never the usage payload) and returns `False`. Order inside the guarded block: validate `api` and `status` (both closed sets; unknown stores nothing, logs the value redacted and truncated, returns `False`), redact text fields (`redaction.redact_text`: `request_id`, `model`, `preset`, `tool`, `project_name`, upstream-tool names, `currency`), sanitize `usage_json` (below), resolve `project_id` with a lookup that never inserts (a missing project stores NULL id and the given name), insert.
**Sanitizing `usage_json`.** The stored text is `json.dumps(raw, allow_nan=False, separators=(",", ":"))` passed through `redact_text` (so a key-shaped token inside any value or key is replaced by `[redacted]`; the key alphabet contains no quote, so the text stays valid JSON, and every other byte is unchanged). A NaN or Infinity makes `dumps` raise `ValueError` (it would otherwise emit invalid-for-strict-parsers JSON that SQLite's JSON functions and the report reject), and a serialization longer than `MAX_USAGE_JSON = 16384` bytes is too large; both store the marker `{"_truncated": true, "_reason": "unserializable"|"oversize", "_original_bytes": <n or null>}` instead. 16 KB is 32 times the 501-byte fixture object, roomy for a dozen upstream tools and still a bound on a hostile or buggy upstream; the typed columns (parsed independently) keep every figure either way. `record_usage` takes `secrets` (default empty) and passes it to `redact_text`; callers pass the configured API key. Without it only key-shaped (`pplx-`) tokens are guaranteed removed, which is enough because the usage object is the provider's accounting structure (numbers and tool names) and does not echo the request, and the API key is the only secret the server holds.
**Parser totality.** `usage_from_agent_response` and `computed_usage` never raise: each sub-field is read through a helper that returns NULL plus a log line for a non-mapping, string, bool, negative, out-of-range (D2 caps) or otherwise malformed value, and the parse call itself is made inside the recorder's guarded block when the caller hands raw usage, so a parser bug cannot reach the tool either.
**Locking and order (the write-lock hazard).** `unit_of_work(write=True)` begins `BEGIN IMMEDIATE`, SQLite's single writer lock. A recorder invoked while the caller's own write unit is still open on the same engine waits `PERPLEXITY_DB_BUSY_TIMEOUT` for a lock its own caller holds, fails `storage_busy` internally and loses the event. So callers record while holding no write unit on that engine, and a tool never holds a write unit across an upstream call (that would also block every other writer for the length of an LLM call, which can be minutes). The caller sequence (D7) is: validate the project name (pure), resolve the project in a short unit that has already committed, upstream call, `record_usage`, then the tool's own write unit. Consequence: a project created by that early unit survives a later failure of the call (an empty project; harmless, stated in the `local-storage` amendment). The hazard is pinned by a test (task 3.5): `record_usage` inside an open write unit returns `False` within the busy timeout.
**Cancellation and coverage.** The write runs as `asyncio.shield`-ed work so cancelling the tool task right after the upstream call does not lose spend that has already happened; the cancellation is re-raised after the write completes. A call cancelled *before* the upstream call returns is not recorded: no response, no usage, and the provider may still bill; this is an accepted gap, stated in the spec. Cost of isolation: a locked database can delay the tool's reply by up to `PERPLEXITY_DB_BUSY_TIMEOUT` (default 5 s); the spec states "delay beyond the busy timeout" never, not "never delay". *Alternative:* fire-and-forget background task. Rejected: lost on shutdown (stdio exits through `os._exit` after draining only in-flight calls) and untestable without sleeps.
*Alternative:* record inside the tool's own unit of work. Rejected: a tool that fails after a costed call would roll the cost back, hiding real spend.

**D7. Recorder contract (what the four later epics call).** Surface kept to one function, one input type, one parser:

```python
# mcp_perplexity_pro/usage.py
@dataclass(frozen=True)
class ToolCallUsage:              # one upstream tool inside one call
    invocations: int | None = None
    cost_nano: int | None = None

@dataclass(frozen=True)
class Usage:                      # parsed facts about one call; every field optional
    cost_nano_usd: int = 0
    cost_source: Literal["reported", "computed", "none"] = "none"
    input_tokens: int | None = None   # ... and the other token/cost columns of D1
    tool_calls: dict[str, ToolCallUsage] = ...   # upstream tool -> invocations, cost_nano
    raw: dict | None = None           # the usage object (-> usage_json after D6 sanitizing)
    price_table: str | None = None

def utcnow() -> datetime                                          # naive UTC, microseconds
def usage_from_agent_response(usage: Mapping | None) -> Usage    # D1 shape, cost 'reported'; never raises
def computed_usage(cost_nano_usd: int, **facts) -> Usage         # cost 'computed', stamps PRICES_AS_OF; never raises

async def record_usage(
    engine: AsyncEngine, *, tool: str, api: str, status: str = "ok",
    usage: Usage | None = None, model: str | None = None, preset: str | None = None,
    request_id: str | None = None, project: str | None = None,
    latency_ms: int | None = None, secrets: Iterable[str] = (),
    clock: Callable[[], datetime] = utcnow,
) -> bool                          # True = stored; never raises
```

The caller pattern (documented in `CLAUDE.md`, exercised by the test-only tool), in the order D6 requires:

```python
name = validate_project_name(project or DEFAULT_PROJECT)       # pure
async with unit_of_work(engine) as session:                    # short; commits before the call
    await get_or_create_project(session, name)
started = time.monotonic()
try:
    response = await ctx.lifespan_context.client.post("/v1/agent", ...)
except PerplexityError as exc:
    await record_usage(
        engine, tool=..., api="agent", status=exc.category, project=name,
        latency_ms=ms(started), secrets=secrets,
    )
    raise
await record_usage(
    engine, tool=..., api="agent", status=<see rules>, usage=usage_from_agent_response(response.usage),
    model=response.model, preset=requested, request_id=response.id, project=name,
    latency_ms=ms(started), secrets=secrets,
)
async with unit_of_work(engine) as session:                    # the tool's own writes, last
    ...
```

Contract rules for callers: record exactly once per costed call that returns or fails with a categorized error; record a failure with its error category and no `usage`; hold no write unit of work when calling `record_usage` and none across the upstream call (D6); for a background run record only the terminal response (the submit and the pending polls carry `usage: null`, same `resp_` id, per fixtures), exactly once per billed run, and **never record a submit or pending response as `ok` with its request id**: that would occupy the dedupe key (D8) with a zero-cost row so the real terminal response is dropped as a duplicate. A terminal response that arrived with HTTP 200 but reports a failed or incomplete run (a `status` other than `completed`, or a non-null `error`; only `completed`, `queued` and null have been observed, so `py-agent-api` confirms the failure vocabulary against a live run) is recorded with status `unexpected_response` and whatever `usage` it reports. *Why this choice:* every fixture (`agent_fast.json`, `agent_background_poll.json`, the error fixture) shows `usage` populated only on completion and no fixture shows what a failed run bills; keeping the reported usage never invents a cost, and `unexpected_response` is the existing category for "the body contradicts the HTTP status" (the alternative, `ok` with the usage, would hide the failure in the error count; recording cost 0 would discard a figure the API itself reported). `project` is the name the tool already resolved through `get_or_create_project`; never pass prompts or bodies (there is no parameter for them). `usage_from_*` parsers for Search, Decisions and Embeddings are written by their own epics after probing the live response (lesson `docs-lie-probe-the-api-first`); they may use `computed_usage(...)` with the `pricing.py` helpers (`search_cost_nano(requests, search_type)`, `embeddings_cost_nano(model, tokens)`, `decisions_cost_nano(input_tokens)`, `agent_tool_cost_nano(tool, invocations)`), each returning `None` for an unknown model or tool so the caller falls back to `Usage()` (source `none`).
`usage_from_agent_response`: reported cost = `cost.total_cost` when it converts (D2), else source `none`; breakdown fields convert individually (absent or malformed stays NULL); `tool_calls` from `tool_calls_details` (invocation, `cost_usd`) with `tool_calls_cost_details` as a cross-check not stored twice; `raw` = the dict. A usage object that is not a mapping yields `Usage()` plus a log line.

**D8. A response is recorded once.** Fixture evidence: `agent_background_submit.json`, `agent_background_poll_pending.json` and `agent_background_poll.json` all have id `resp_caf1d3f9-3489-4a09-a6d8-3aafd929e535`, and only the last has `usage`. A user asking for a finished job's result twice would otherwise double-count it. Enforced by a partial unique index on `(api, request_id)` where `request_id IS NOT NULL AND status = 'ok'`, and the insert is `INSERT ... ON CONFLICT DO NOTHING`; the recorder returns `False` for the duplicate (logged at debug, not warning). Failed calls are not deduplicated (they usually carry no id). **Edge cases:** (a) two different key-shaped ids redact to the same `[redacted]` text, so the second distinct response is dropped as a duplicate; accepted because an upstream id that is key-shaped is itself abnormal and the drop is logged at debug; (b) an upstream that reuses a response id for a genuinely new billed run (not observed) would lose the second event, the cost of keying on the id; (c) a repeated poll of a *failed* terminal response (`unexpected_response`, which the index does not cover) records a row per poll, so callers record a terminal failure once, like a success. Dedupe applies only to status `ok`; a failure never blocks a later success with the same id.

**D9. Parsers are not written for APIs we have not probed.** Only the Agent shape is fixture-backed. The recorder's input type is generic on purpose, so py-search-api, py-decisions-tool and py-embeddings each add a parser plus a fixture, not a schema change (every typed column is already nullable). If one of them finds a field the columns lack, `usage_json` still holds it and a later migration can promote it.

**D10. Reporting tool `perplexity_usage`** (`tools/usage.py`, same layout as `tools/models.py`): typed `Annotated[..., Field(description=...)]` parameters `project: str | None`, `since: str | None`, `until: str | None` (strict `YYYY-MM-DD`: a regex `\d{4}-\d{2}-\d{2}` then `date.fromisoformat`, because pydantic's `date` parsing also accepts timestamps and integers; a bad one, or an `until` of `9999-12-31` whose `+ 1 day` bound overflows `date`, is raised as `invalid_request` by the tool, never left to surface as `internal_error`), `group_by: Literal["tool","api","model","project","day"] = "tool"`, `limit: int = 20` (1-200, checked in the tool so the error is `invalid_request`). Output model `UsageResult`: `totals` (calls, errors, input/output/total tokens, `cost_nano_usd: int`, `cost_usd: str`, `calls_cost_computed`, `calls_cost_unknown`: every call with cost source `none`, errors included), `group_by`, `groups` (key plus the same measures), `groups_total`, `groups_truncated`, plus the echoed filters. Annotations `readOnlyHint=True, idempotentHint=True, openWorldHint=False`. One read-only unit of work (`write=False`), SQL aggregation with `SUM`/`COUNT` over integers, so totals are exact and are computed over all matching rows in a query separate from the (limited) group query. Date filter is `created_at >= 'YYYY-MM-DD 00:00:00'` and `created_at < <until + 1 day> 00:00:00` on naive-UTC values (the same convention as `projects.created_at`; `created_at` is always written by the recorder as naive UTC so comparisons are lexical-safe). `day` key is `date(created_at)`. **Grouping is a whitelist, not interpolation:** a module-level dict maps `tool -> "tool"`, `api -> "api"`, `model -> "model"`, `project -> "project_name"`, `day -> "date(created_at)"` to fixed SQL fragments, the query function raises `ValueError` for a key not in the dict, and no caller text is ever placed in SQL. **`day` with `limit`:** the group query selects the latest N days (`ORDER BY day DESC LIMIT N`) and the result is then sorted ascending, so a long history shows the newest days, not the oldest; `groups_total` and `groups_truncated` are as for other groupings. **Lower bound:** error rows count cost 0 but may have been billed (D3), so `cost_nano_usd` is a lower bound; the tool description and the text rendering say so, and `calls_cost_unknown` includes errors so the figure that discloses it is not understated. The project filter matches `project_name`; no project lookup happens, so it never creates one and a deleted project reports normally. Token sums treat NULL as 0 (documented in the tool description). The tool itself is not recorded (it makes no upstream call). The text rendering is a small fixed table: totals line, then `key | calls | errors | tokens | cost USD`.

**D11. Tool and file layout.** `pricing.py`, `usage.py` (money helpers, `Usage`, parser, recorder), `tools/usage.py`, `UsageEvent` in `storage/models.py`, `migrations/versions/0002_usage_events.py`. `server.py` is unchanged: the recorder takes the engine, which tools already reach through `ctx.lifespan_context.engine`.

**D12. No settings, no off switch.** A recording switch would let a misconfiguration silently drop the data this epic exists to collect, and the recorder is already failure-isolated. If a real need appears (privacy, disk), add `PERPLEXITY_USAGE_LOG` then.

**D13. Tests use a test-only caller and real fixtures.** A tool registered only by the test (the foundation pattern; `tests/conftest.py`'s test-only `notes` table plays the same role for deletion) calls an `httpx2.MockTransport` that serves `agent_fast.json` or a failure fixture, then records. This proves the contract end to end without a production caller. Mutation checks per `docs/lessons/cleanup-tests-must-fail-when-cleanup-is-removed.md`: the isolation test must go red when the `try/except` is removed, the retained-table test when the `SET NULL` branch is removed.

## Risks / Trade-offs

- **Only the Agent usage shape is real** → the recorder input is generic, later epics probe first (D9); a wrong assumed alias for upstream-tool names only affects the `computed` fallback.
- **Computed prices rot** (Perplexity changes prices) → every computed event stores `price_table`, a test pins the constants to the dated page, and prices are used only when no cost is reported.
- **Recording delays a reply by up to the busy timeout when the database is locked** → accepted and stated in the spec; the write is a single small insert under `BEGIN IMMEDIATE`.
- **Shielded write on cancellation** keeps the cancelled call alive a little longer → bounded by the same busy timeout; without it spend is lost on client disconnects.
- **Detach vs. cascade depends on PRAGMA output** (not the SQLAlchemy inspector) → a test pins `on_delete` parsing for SET NULL, CASCADE and NO ACTION so a SQLite or SQLAlchemy change fails loudly; the explicit `UPDATE` makes the behavior independent of `PRAGMA foreign_keys`.
- **A recreated project name looks like the old one in reports** → by design (history by name); `project_id` NULL marks pre-deletion events.
- **Events lost at shutdown** → the shielded write is not an in-flight request, so the 10 s drain does not wait for it; a call whose recording is mid-write when the process exits can lose its event (also cancelled-before-return calls, D6). Accepted: bounded to the final milliseconds of one write per in-flight call; best effort is the stated contract.
- **Dedupe-index edge cases** (D8: two key-shaped ids collapsing, an upstream reusing an id, repeated failure polls) → each documented with its accepted effect; none lets the recorder raise.
- **A project created before the upstream call survives a later failure** (D6 ordering) → an empty project row; harmless, and stated in the `local-storage` amendment instead of hidden.
- **A recorder called inside an open write unit loses the event** (stalls the busy timeout) → pinned by a test and by the caller contract; the recorder cannot detect it from outside.
- **Unbounded growth** → documented non-goal; the `created_at` index keeps a later prune cheap.
- **`none` is a third cost source the brief did not name** (D3) → reviewers should confirm; it can be folded into `computed` only by lying about failures.
- **Downgrading drops `usage_events` and the spend history with it** → the automatic pre-migration backup covers upgrades only; the README names this under the backup procedure.
- **Two-hop deletion count caveat unchanged**: rows in tables that point at a retained table (none today) are neither removed nor detached; a retained table's own children would need their own rule when one appears.

## Migration Plan

1. Land table, pricing, recorder and deletion interplay behind tests with the test-only caller; no production behavior changes except `perplexity_projects delete` reporting a detached count.
2. Add `perplexity_usage`; on the live server it reports zero until a costed tool exists.
3. Upgrading a 0001 database takes the automatic backup (`backup-0001.db`), applies 0002 inside the migration transaction and refuses a failed migration as foundation specified. Rollback: `0002` downgrade drops the table (history lost; restore from the backup only if a pre-upgrade state is wanted), or revert the merge.
4. Each later epic wires `record_usage` into its tools as part of its own change.

## Open Questions

- Whether Search, Decisions and Embeddings responses report a cost (answered per epic by the live probe; does not change this change's schema or specs).
- The upstream-tool keys other than `search_web` in `usage.tool_calls_details` (py-agent-api to confirm).

## Observed shapes (the evidence for D1, D2, D8)

From `tests/fixtures/agent_fast.json` (captured 2026-10-09, preset `fast`, resolved model `openai/gpt-6-luna`): `usage` is 501 bytes compact; 3426 input tokens of which 1643 `cache_creation_input_tokens` and 1780 `cache_read_input_tokens` (equal to `cached_tokens`), 30 output, 3456 total, 0 reasoning; `cost` has `input_cost 0`, `output_cost 0.00002`, `cache_read_cost 0.00002`, `cache_creation_cost 0.00021`, `tool_calls_cost 0.001`, `total_cost 0.00125`, `currency "USD"`; `tool_calls_details.search_web = {cost_usd: 0.001, invocation: 1}`. `agent_background_poll.json` (same preset, completed): no `cache_creation_cost`, 3423 cache-read tokens, `total_cost 0.00105`. The submit and pending poll responses have `usage: null`, status `queued`, `model: "fast"` (the preset name) and the same id as the completed poll, which carries the resolved model. Costs are floats; token counts are integers; `input_cost` is 0 although the call had 3426 input tokens, apparently because all but a few input tokens were cache reads or writes billed in their own fields (an inference from the fixture, not documented), so a total cannot be recomputed from `input_tokens`.

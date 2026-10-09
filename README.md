# MCP Perplexity Pro

An [MCP](https://modelcontextprotocol.io) server for the Perplexity API, written in Python
(FastMCP, SQLAlchemy, SQLite). It serves MCP over stdio or Streamable HTTP and keeps its own data
in a local SQLite database.

## Status: 2.0.0

Version 2.0.0 replaces the TypeScript 1.x server. The reason is that Perplexity retired the Sonar
endpoints the 1.x server called: both `POST /chat/completions` and `GET /async/chat/completions`
now return `403 chat_completions_not_available` ("Sonar is now the Agent API"), so 1.x could not
answer a single query. There was no working behavior to port, so the TypeScript code is deleted
(git history keeps it) and the server was rebuilt in Python on the Agent API (`POST /v1/agent`).

**Seven tools exist today:**

| Tool | What it does | Spends money |
|---|---|---|
| `perplexity_ask` | One web-grounded question, answered synchronously with its sources. Depth `fast` (default), `low` or `medium` | yes |
| `perplexity_chat` | A multi-turn conversation kept in the local database: `send`, `list`, `read`, `delete` | `send` only |
| `perplexity_research` | Starts a deep research run in the background and returns a job id at once. Depth `medium` (default), `high` or `xhigh` | yes, when a call observes the run finish |
| `perplexity_jobs` | Manages research runs: `list`, `status`, `result`, `cancel` | no new spend; it records the finished run's |
| `perplexity_models` | Lists the models your key can use, with live prices, plus the documented Agent API presets | no |
| `perplexity_projects` | Lists projects, or deletes one and its stored records (spend history is kept) | no |
| `perplexity_usage` | Reports what recorded upstream calls cost, grouped by tool, API, model, project or day. Read-only | no |

**The four Agent tools record their usage.** Every costed upstream call stores one usage event
(`perplexity_usage` reports them), and a background research run is recorded once, by the first
`perplexity_jobs` call that sees it finish. The Search, Embeddings and Decisions tools arrive in
later releases and will each record their calls the same way.

**These tools can spend money, and there is no cost ceiling.** Defaults are the cheapest depths
(`fast`; `medium` for research). `high` and `xhigh` exist only behind `perplexity_research`
because a single run can cost dollars (see "Cost by depth").

The old tool names (`ask_perplexity`, `chat_perplexity` and the rest) are gone and are not coming
back under those names. No data is imported from 1.x.

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
| `PERPLEXITY_AGENT_READ_TIMEOUT` | `120` | Seconds to wait for a synchronous Agent run (`perplexity_ask`, `perplexity_chat` send). A background submit and every other request use `PERPLEXITY_READ_TIMEOUT`. Must be greater than 0 |
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

Four tools (`perplexity_ask`, `perplexity_chat`, `perplexity_research`, `perplexity_jobs`) call the
Perplexity Agent API (`POST /v1/agent`) and spend money. The first three sections below are what
applies to all four; each tool follows.

### Cost by depth

A depth is an Agent API preset: a bundle of model, search tools and step budget. You choose it;
nothing is routed automatically and there is **no spending cap**. Costs are the exact figures the
API reported in its responses (`usage.cost_usd`, `cost_source: "reported"`), not estimates, except
where the table says "not measured".

| Depth | Where it is available | Observed cost per call | Evidence | Observed time |
|---|---|---|---|---|
| `fast` (default for ask and chat) | `perplexity_ask`, `perplexity_chat` | $0.00118 to $0.00180 | Live acceptance run, 2026-10-09: $0.00143, $0.00118, $0.00158. Probe fixtures, 2026-10-09 (the eight `fast` captures in `tests/fixtures/`): $0.00119 to $0.00180 | 1.7 to 2.6 s (acceptance) |
| `low` | `perplexity_ask`, `perplexity_chat` | $0.00045 to $0.00386 | Acceptance, 2026-10-09: $0.00156 (one call, 3.2 s). Probe fixtures, 2026-10-09: $0.00045 (`agent_chat_depth_switch.json`, a chained chat turn) and $0.00386 (`agent_low_fetch_url.json`, a call that fetched a page). Up to about $0.02 is the probe report's range; it is not backed by a saved capture | 3.2 s (acceptance) |
| `medium` | `perplexity_research` (background); `perplexity_ask` and `perplexity_chat` accept it too | $0.01599 to $0.01722 as a research run | Acceptance, 2026-10-09: $0.01722 (job 1, 39 s between our submit and the call that saw it finish). Probe fixture `agent_background_completed.json`, 2026-10-09: $0.01599. About $0.05 as an upper figure is the probe report's range; not backed by a saved capture. A synchronous `medium` call was not run in either | about 35 to 40 s |
| `high` | `perplexity_research` only | not measured | Never run. "Up to about $0.4 to $0.9, and minutes" is the probe report's and the provider's own positioning: an estimate | minutes (estimate) |
| `xhigh` | `perplexity_research` only | not measured | Never run; more than `high` | minutes (estimate) |

Two things the table cannot show. A **cancelled** run reports no usage, so its cost is unknown (the
probe's cancelled run had already run six searches); the usage report counts it as an error with an
unknown cost. And a run's cost grows with what it searches and fetches, so the same depth costs
different amounts for different questions. Check `perplexity_usage` after trying a new kind of
question.

**Why `high` and `xhigh` exist only behind `perplexity_research`.** They can cost dollars and last
minutes, and the API sits behind Cloudflare, whose default read timeout (100 s) was not verified for
this API, so a long synchronous request may be cut. A synchronous call that is cut may still be
billed. `perplexity_ask` and `perplexity_chat` therefore
refuse both depths with `invalid_request` and point to `perplexity_research`, where the run is
background, observed later, and can be cancelled.

### What `store: false` does and does not do

`perplexity_ask` and `perplexity_chat` send `store: false`. **That is not a retention control.**
The provider's documentation says it "only hides a response from retrieval" and does not disable
persistence, so the provider may still keep the query and answer. Do not rely on it to keep text
away from Perplexity. The chat tool uses it because a `store: false` response can still be
continued from (measured on 2026-10-09 for three chained turns), not for privacy.

**Research runs are stored by the provider.** `perplexity_research` sends `store: true`, because a
background run that is not stored cannot be retrieved. The query and result stay retrievable at the
provider. This server also keeps the query and the result in its own local database
(`perplexity.db`, mode 0600), as it does chat text.

### Sources are not citations

`sources` lists the pages the run found or fetched, de-duplicated by URL, in order of first use,
each with `url`, `title`, `date` (when the page has one) and `id`. It is **not** a list of what
the answer cited. The API's `annotations` field was empty in every captured response, so nothing
ties a claim to a source: the inline markers in the answer (`[1]`, `[web:0]`, markdown links) are
returned unchanged and are **not** mapped to `sources` entries (the markers are not numbered like
the `id`s, and nothing documents the mapping). A source may be unused by the answer, and an answer
may rest on a page that is not listed.

### `perplexity_ask`

One web-grounded question, answered synchronously and statelessly. It never waits for a background
run. A `completed` or `incomplete` run returns a result; any other status is an
`unexpected_response` error (the call is still recorded, because it was billed).

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `query` | string | required | The question, not blank, at most 20000 characters |
| `project` | string | `default` | The project the call is recorded under; created if absent |
| `depth` | `fast`, `low` or `medium` | `fast` | The preset. `high` and `xhigh` are refused (see "Cost by depth"). Cannot be combined with `model` |
| `model` | string | none | An explicit model id (for example `openai/gpt-6-luna`) instead of a depth. It searches with the web search tool and a 3-step budget unless `search` is false. An Anthropic id gets `max_output_tokens` 4096 unless you set one |
| `search` | boolean | none | `false` answers from the model alone and needs `model` (a depth always searches). `true` is accepted and changes nothing |
| `domains` | list of strings | none | At most 20 domains to search: all allowed (`python.org`) or all denied with a `-` prefix (`-reddit.com`). Mixing the two is refused |
| `recency` | `hour`, `day`, `week`, `month` or `year` | none | Only recent results |
| `after`, `before` | string `YYYY-MM-DD` | none | Only results published after or before this date. A malformed date is refused locally |
| `country` | string | none | Two-letter country code to localize the search (`US`) |
| `max_results` | integer 1 to 50 | none | Search results to retrieve |
| `instructions` | string | none | System-style instructions, at most 10000 characters |
| `max_output_tokens` | integer 1 to 64000 | none | Cap on answer tokens. A run that hits it is `incomplete` |
| `json_schema` | object | none | A JSON Schema whose root type is `object`, at most 20000 characters serialized, for a structured answer. The parsed answer is `answer_json` |

A search filter (`domains`, `recency`, `after`, `before`, `country`, `max_results`) replaces the
preset's own tools with the web search tool alone, so a filtered `medium` run loses the preset's
page fetching. The filters are validated here because the API accepts some invalid input silently
(a mixed allow and deny list, a date in the wrong format) and would run, and bill, a call that
ignored it.

Output (`structuredContent`, with the answer, a numbered source list and one usage line as text):

| Key | Meaning |
|---|---|
| `answer` | The answer text; inline markers are unchanged |
| `answer_json` | The parsed answer when `json_schema` was given and the text parsed, else `null` |
| `sources` | Pages the run found or fetched (see "Sources are not citations") |
| `status` | `completed` or `incomplete` |
| `incomplete_reason` | Why an incomplete run stopped, for example `max_output_tokens`; otherwise `null` |
| `warnings` | Things worth knowing about this result |
| `model` | The model that answered |
| `depth` | The preset used; `null` when `model` was given |
| `response_id` | The API's response id |
| `usage` | `input_tokens`, `output_tokens`, `total_tokens`, `cost_usd` (an exact decimal string, `null` when unknown) and `cost_source` (`reported`, `computed` or `none`) |
| `latency_ms` | Measured wall time of the upstream call |
| `project` | The project the call was recorded under |

An `incomplete` answer is a result with a warning, not an error: the run happened and was billed.
An invalid `json_schema` makes the API answer with the same generic `400 invalid request` it gives
for other mistakes, so the error message names the schema only as the likely cause.

Example, `fast` with a domain filter. The result is from the live acceptance run on 2026-10-09
(`openspec/changes/py-agent-api/acceptance/a1.json`), shortened to 3 of its 10 sources; nothing
else is edited. The acceptance files hold results, not requests, so every example call in this
README is written to match its result (depth, project and the fields the result shows); where a
result does not repeat the query, the query text is illustrative:

```json
{"name": "perplexity_ask", "arguments": {"query": "What is the latest stable Python release?", "depth": "fast", "domains": ["python.org"], "project": "acceptance"}}
```

```json
{
  "answer": "The latest stable Python release is **Python 3.15.0**, released October 9, 2026.[1]",
  "answer_json": null,
  "sources": [
    {"url": "https://www.python.org/downloads/release/python-3150/", "title": "Python Release Python 3.14.8 | Python.org", "date": null, "id": 1},
    {"url": "https://www.python.org/doc/versions/", "title": "Python documentation by version", "date": "2016-03-13", "id": 2},
    {"url": "https://devguide.python.org/versions/", "title": "Status of Python versions", "date": "2026-05-27", "id": 3}
  ],
  "status": "completed",
  "incomplete_reason": null,
  "warnings": [],
  "model": "openai/gpt-6-luna",
  "depth": "fast",
  "response_id": "resp_902df360-29f3-4568-b1f6-b78f6cdb7797",
  "usage": {"input_tokens": 3298, "output_tokens": 30, "total_tokens": 3328, "cost_usd": "0.00143", "cost_source": "reported"},
  "latency_ms": 2011,
  "project": "acceptance"
}
```

The same file's `low` run (`a2.json`), keys shortened to the ones that differ (it returned 15
sources and cost more than `fast`):

```json
{"name": "perplexity_ask", "arguments": {"query": "What is FastMCP?", "depth": "low", "project": "acceptance"}}
```

```json
{
  "answer": "FastMCP is a Python framework for building Model Context Protocol (MCP) servers, clients, and interactive applications that connect AI models to tools and data. [web:1]",
  "status": "completed",
  "model": "openai/gpt-6-luna",
  "depth": "low",
  "usage": {"input_tokens": 5464, "output_tokens": 95, "total_tokens": 5559, "cost_usd": "0.00156", "cost_source": "reported"},
  "latency_ms": 3156,
  "project": "acceptance"
}
```

### `perplexity_chat`

A multi-turn conversation kept in the local database, with four actions. The messages are stored in
this server's `perplexity.db`, project-scoped. Only `send` calls the API and spends money; `list`,
`read` and `delete` touch only the local database, and none of them ever creates a project (a
by-id action in an absent project is `not_found`; `list` in one is empty).

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `action` | `send`, `list`, `read` or `delete` | required | What to do |
| `message` | string | none | `send`: the message, not blank, at most 20000 characters |
| `title` | string | none | `send` starting a chat: its title, 1 to 120 characters, required. Not allowed with `chat_id` |
| `chat_id` | integer | none | `send`: continue this chat; omit it to start a new one. `read` and `delete`: the chat |
| `project` | string | `default` | The project the chat belongs to |
| `replay` | boolean | `false` | `send` with `chat_id`: resend the stored history instead of continuing from the previous response (see below) |
| `depth`, `model`, `search`, `domains`, `recency`, `after`, `before`, `country`, `max_results`, `instructions`, `max_output_tokens` | as in `perplexity_ask` | as there | `send` only. `depth` may change on every turn; `high` and `xhigh` are refused. There is no `json_schema` |
| `limit` | integer | 20 (`list`), 50 (`read`) | `list`: chats to return, 1 to 100, newest first. `read`: the last N messages, 1 to 200 |
| `confirm` | boolean | `false` | `delete` needs `true`; removing a chat cannot be undone |

A `send` continues from the last stored response with `previous_response_id`, sending only the new
message, so the cost of a turn does not grow with the history. **`replay`** is the fallback: it
resends the whole stored history (and, with it, every stored character as input on every turn).
The provider rejects an unknown, expired, unfinished or cancelled `previous_response_id` with one
generic `400 invalid request`; when that happens on a chained send, the error says the provider
could not continue and to send again with `replay: true`. The server does not retry by itself,
because a hidden second call would double the bill. A replay of more than 100000 stored characters
adds a warning that every send costs more. Only `completed` turns are stored; an `incomplete`
answer is returned with a warning (it was billed) and is not saved, and an incomplete first send
creates no chat (`chat_id` is `null`).

Output of `send` has every `perplexity_ask` key except `answer_json` (always `null` here) plus:

| Key | Meaning |
|---|---|
| `action`, `project` | The action and the project |
| `chat_id`, `chat` | The chat the call concerns (the new one for a first send) and its record: `id`, `title`, `message_count`, `created_at`, `updated_at` |
| `continuation` | `new`, `chained` (from the last response id) or `replay` |

`list` returns `chats` (newest first), `chats_total` and `truncated`. `read` returns `chat`,
`messages` (each with `id`, `role`, `content`, `created_at` and, for the assistant, `response_id`,
`model`, `preset` and `sources`), `messages_total` and `truncated`. `delete` returns
`messages_removed`. Keys an action does not use are `null`. A chat whose answer could not be
stored after a billed call still returns the answer, with a `not_saved` warning; the usage event
is kept.

Example, two turns in a new chat. The results are from the live acceptance run on 2026-10-09
(`c1.json` and `c2.json`), shortened to the keys shown and, for the first, 2 of its 10 sources.
Turn 2 answers from turn 1 through the stored response id (`"continuation": "chained"`):

```json
{"name": "perplexity_chat", "arguments": {"action": "send", "title": "acceptance chat", "message": "Remember this codeword for later: HERON-7. Just reply OK.", "project": "acceptance"}}
```

```json
{
  "action": "send",
  "project": "acceptance",
  "chat_id": 1,
  "chat": {"id": 1, "title": "acceptance chat", "message_count": 2, "created_at": "2026-10-09T21:51:07.605016Z", "updated_at": "2026-10-09T21:51:07.605016Z"},
  "continuation": "new",
  "answer": "OK",
  "sources": [
    {"url": "https://sharpe.co.za/tools/code-word-generator/", "title": "Code Word Generator: a private phrase your family can say ...", "date": null, "id": 1},
    {"url": "https://militaryalphabet.net/", "title": "Military Alphabet - NATO Phonetic Alphabet - Communication", "date": "2025-05-05", "id": 2}
  ],
  "status": "completed",
  "model": "openai/gpt-6-luna",
  "depth": "fast",
  "usage": {"input_tokens": 3073, "output_tokens": 5, "total_tokens": 3078, "cost_usd": "0.00118", "cost_source": "reported"},
  "latency_ms": 1689
}
```

```json
{"name": "perplexity_chat", "arguments": {"action": "send", "chat_id": 1, "message": "What was the codeword?", "project": "acceptance"}}
```

```json
{
  "chat_id": 1,
  "chat": {"id": 1, "title": "acceptance chat", "message_count": 4, "created_at": "2026-10-09T21:51:07.605016Z", "updated_at": "2026-10-09T21:51:10.265646Z"},
  "continuation": "chained",
  "answer": "Your codeword is HERON-7.",
  "model": "openai/gpt-6-luna",
  "depth": "fast",
  "usage": {"input_tokens": 7583, "output_tokens": 55, "total_tokens": 7638, "cost_usd": "0.00158", "cost_source": "reported"},
  "latency_ms": 2613
}
```

### `perplexity_research`

Starts a deep research run **in the background** and returns at once with a job id. Nothing ever
waits for a run to finish: read progress and the answer with `perplexity_jobs`.

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `query` | string | required | The research question, not blank, at most 20000 characters |
| `depth` | `medium`, `high` or `xhigh` | `medium` | Deeper runs take longer and cost more (see "Cost by depth"). `fast` and `low` belong to `perplexity_ask` |
| `instructions` | string | none | System-style instructions, at most 10000 characters |
| `project` | string | `default` | The project the job belongs to; created if absent |

Output: `job_id` (the local id, for `perplexity_jobs`), `response_id`, `status` (what the provider
reported, usually `queued` or `in_progress`), `depth`, `project`, `started_at` (UTC, this server's
clock) and `message`. A run that had already finished when it was submitted is stored finished and
recorded at once.

**A run is recorded as spend only when a `perplexity_jobs` call sees it finished.** The submit is
not recorded (the cost is unknown until the run ends). See "The unobserved-run gap" below.

Example, from the live acceptance run on 2026-10-09 (`r1.json`, unedited). The query's first 120
characters are the job's `query_excerpt` in `j2.json`; the rest is illustrative:

```json
{"name": "perplexity_research", "arguments": {"query": "Compare the pricing models of Pinecone, Weaviate Cloud and Qdrant Cloud using current official pricing pages. Short table.", "depth": "medium", "project": "acceptance"}}
```

```json
{
  "job_id": 1,
  "response_id": "resp_f607dfc5-a69a-44cd-9e45-43cb0587af76",
  "status": "queued",
  "depth": "medium",
  "project": "acceptance",
  "started_at": "2026-10-09T21:51:17.475891Z",
  "message": "The run is going in the background. Check it with perplexity_jobs status, or list with refresh true; it is recorded as spend when a call sees it finished."
}
```

### `perplexity_jobs`

Manages the runs started by `perplexity_research`. No action waits for a run to progress: call
again later. An action never creates a project (`list` in an absent project is empty; the others
are `not_found`), and a job id from another project is `not_found`.

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `action` | `list`, `status`, `result` or `cancel` | required | What to do |
| `job_id` | integer | none | `status`, `result`, `cancel`: the job from `perplexity_research` |
| `project` | string | `default` | The project the job belongs to |
| `refresh` | boolean | `false` | `list`: first observe the project's running jobs, up to 10, least recently checked first |
| `limit` | integer | 20 | `list`: jobs to return, 1 to 100, newest first |

- `status` fetches a running job once, stores what it shows and reports progress (`progress.searches`,
  `progress.fetches`). A job that is already finished is served from the local database with no
  request.
- `result` does the same, and returns the stored `answer`, `sources` and `usage` of a finished
  job. For a run that ended without an answer (`cancelled`, `failed`, `incomplete`, `lost`) the
  `message` says why. A run that is not finished returns no answer and a message to try again.
- `cancel` fetches first, then cancels a running job at most once (a second call while the cancel
  is pending sends no second request). The result's `status` is `cancelling`; the run turns
  `cancelled` after a few more polls, so call `status` afterwards. Cancelling stops the run for good.
- `list` returns `jobs` (each with `job_id`, `response_id`, `depth`, `status`, `query_excerpt`,
  `model`, `started_at`, `finished_at`, `cancel_requested_at`, `usage_recorded`), `jobs_total` and
  `truncated`. With `refresh`, `not_refreshed` counts running jobs that were not refreshed (beyond
  10, or whose fetch failed; a failed one is also a warning naming the job).

A job's `status` is `queued`, `in_progress`, `completed`, `failed`, `incomplete`, `cancelled`,
`lost` or an unknown provider status verbatim. `lost` means the provider no longer knows the run:
it needs a second not-found answer at least 10 minutes after submit, and its spend cannot be
recorded. `cancelling` is only ever reported by `cancel`, never stored. `usage_recorded` says a
usage event was attempted for the run (best effort: `perplexity_usage` shows what was stored), and
is always `false` for a lost job.

**The unobserved-run gap.** The first `perplexity_jobs` call that sees a run finished records its
cost, once (overlapping calls record one event). Nothing watches in the background, so a run that
nobody observes is never recorded: the provider ran and billed it, and `perplexity_usage` knows
nothing. `perplexity_jobs list` with `refresh: true` settles up to 10 running jobs in one call and
is the way to close the gap; use it after starting runs you do not plan to read. Once a job is observed finished, its result is
served from the local database and stays readable; a run nobody observes can still be fetched
while the provider keeps it, and becomes `lost` if the provider forgets it. The times a job carries (`started_at`, `finished_at`) are this server's clock, not the
API's: the API rewrites its own timestamps on every fetch. `finished_at` is when a call saw the
run finish, so it is an upper bound on when it did.

**Deleting a project that still has running research jobs** (`perplexity_projects delete`) discards
their local rows, so the spend of those runs is never recorded while the provider keeps running and
billing them; the delete result reports how many as `running_jobs`, and the confirmation message
names them. Cancel them first.

Example, from the live acceptance run on 2026-10-09: the result of job 1 (`j2.json`, answer
shortened to 160 characters and sources to 2 of 30), the cancel of job 2 and the `status` call
after it (`k1.json`, `k2.json`, shortened to the keys shown), and the list (`jl.json`). Job 2's
query was "Summarize the history of the Python programming language in five bullet points with
sources." A cancelled run reports no usage; it was recorded with an unknown cost.

```json
{"name": "perplexity_jobs", "arguments": {"action": "result", "job_id": 1, "project": "acceptance"}}
```

```json
{
  "action": "result",
  "project": "acceptance",
  "job_id": 1,
  "status": "completed",
  "job": {"job_id": 1, "response_id": "resp_f607dfc5-a69a-44cd-9e45-43cb0587af76", "depth": "medium", "status": "completed", "query_excerpt": "Compare the pricing models of Pinecone, Weaviate Cloud and Qdrant Cloud using current official pricing pages. Short tabl", "model": "openai/gpt-6-luna", "started_at": "2026-10-09T21:51:17.475891Z", "finished_at": "2026-10-09T21:51:56.461160Z", "cancel_requested_at": null, "usage_recorded": true},
  "answer": "| Provider | Pricing model |\n|---|---|\n| **Pinecone** | **Starter:** free with usage limits. **Builder:** $20/month flat, with included usage limits. **Standard...",
  "sources": [
    {"url": "https://www.pinecone.io/pricing/", "title": "Pricing - Pinecone", "date": null, "id": 21},
    {"url": "https://www.pinecone.io/pricing/estimate/", "title": "Pricing", "date": null, "id": 22}
  ],
  "usage": {"input_tokens": 25474, "output_tokens": 974, "total_tokens": 26448, "cost_usd": "0.01722", "cost_source": "reported"}
}
```

```json
{"name": "perplexity_jobs", "arguments": {"action": "cancel", "job_id": 2, "project": "acceptance"}}
```

```json
{
  "action": "cancel",
  "job_id": 2,
  "status": "cancelling",
  "job": {"job_id": 2, "response_id": "resp_76ef65be-0662-4ad7-8c3c-dfd4bac61317", "depth": "medium", "status": "in_progress", "query_excerpt": "Summarize the history of the Python programming language in five bullet points with sources.", "model": null, "started_at": "2026-10-09T21:52:04.115117Z", "finished_at": null, "cancel_requested_at": "2026-10-09T21:52:07.375264Z", "usage_recorded": false},
  "progress": {"searches": 1, "fetches": 0},
  "message": "The cancel was accepted. The run turns cancelled after a few more polls: call status to see it and to record its spend."
}
```

```json
{"name": "perplexity_jobs", "arguments": {"action": "status", "job_id": 2, "project": "acceptance"}}
```

```json
{
  "action": "status",
  "job_id": 2,
  "status": "cancelled",
  "job": {"job_id": 2, "response_id": "resp_76ef65be-0662-4ad7-8c3c-dfd4bac61317", "depth": "medium", "status": "cancelled", "query_excerpt": "Summarize the history of the Python programming language in five bullet points with sources.", "model": null, "started_at": "2026-10-09T21:52:04.115117Z", "finished_at": "2026-10-09T21:52:11.813305Z", "cancel_requested_at": "2026-10-09T21:52:07.375264Z", "usage_recorded": true},
  "progress": {"searches": 2, "fetches": 0}
}
```

```json
{"name": "perplexity_jobs", "arguments": {"action": "list", "project": "acceptance"}}
```

```json
{
  "action": "list",
  "project": "acceptance",
  "jobs": [
    {"job_id": 2, "response_id": "resp_76ef65be-0662-4ad7-8c3c-dfd4bac61317", "depth": "medium", "status": "cancelled", "query_excerpt": "Summarize the history of the Python programming language in five bullet points with sources.", "model": null, "started_at": "2026-10-09T21:52:04.115117Z", "finished_at": "2026-10-09T21:52:11.813305Z", "cancel_requested_at": "2026-10-09T21:52:07.375264Z", "usage_recorded": true},
    {"job_id": 1, "response_id": "resp_f607dfc5-a69a-44cd-9e45-43cb0587af76", "depth": "medium", "status": "completed", "query_excerpt": "Compare the pricing models of Pinecone, Weaviate Cloud and Qdrant Cloud using current official pricing pages. Short tabl", "model": "openai/gpt-6-luna", "started_at": "2026-10-09T21:51:17.475891Z", "finished_at": "2026-10-09T21:51:56.461160Z", "cancel_requested_at": null, "usage_recorded": true}
  ],
  "jobs_total": 2,
  "truncated": false
}
```

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
costed upstream call, stored by the server itself) and never writes. The four Agent tools record
their calls (`perplexity_ask`, `perplexity_chat` send and `perplexity_research`, whose background
runs are recorded when a `perplexity_jobs` call sees them finish); the totals are zero on a fresh
install and until one of them runs. The Search, Embeddings and Decisions tools will record theirs
the same way when they arrive.

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

Example call and result, from the live acceptance run on 2026-10-09 (`u_tool.json`, unedited):
six real calls in the project `acceptance` (2 ask, 2 chat, 2 research, one of them the cancelled
run). Your totals will differ:

```json
{"name": "perplexity_usage", "arguments": {"project": "acceptance", "group_by": "tool"}}
```

```json
{
  "totals": {"calls": 6, "errors": 1, "input_tokens": 44892, "output_tokens": 1159, "total_tokens": 46051, "cost_nano_usd": 22970000, "cost_usd": "0.02297", "calls_cost_computed": 0, "calls_cost_unknown": 1},
  "group_by": "tool",
  "groups": [
    {"calls": 2, "errors": 1, "input_tokens": 25474, "output_tokens": 974, "total_tokens": 26448, "cost_nano_usd": 17220000, "cost_usd": "0.01722", "calls_cost_computed": 0, "calls_cost_unknown": 1, "key": "perplexity_research"},
    {"calls": 2, "errors": 0, "input_tokens": 8762, "output_tokens": 125, "total_tokens": 8887, "cost_nano_usd": 2990000, "cost_usd": "0.00299", "calls_cost_computed": 0, "calls_cost_unknown": 0, "key": "perplexity_ask"},
    {"calls": 2, "errors": 0, "input_tokens": 10656, "output_tokens": 60, "total_tokens": 10716, "cost_nano_usd": 2760000, "cost_usd": "0.00276", "calls_cost_computed": 0, "calls_cost_unknown": 0, "key": "perplexity_chat"}
  ],
  "groups_total": 3,
  "groups_truncated": false,
  "project": "acceptance",
  "since": null,
  "until": null,
  "limit": 20
}
```

The text content of the same result:

```
Usage for project acceptance: 6 call(s), 1 error(s), 46051 token(s), cost 0.02297 USD (22970000 nano-USD).
The cost is a lower bound: error calls count cost 0 and may have been billed; 1 call(s) have no known cost and 0 cost(s) were computed from documented prices.
By tool: key | calls | errors | tokens | cost USD
perplexity_research | 2 | 1 | 26448 | 0.01722
perplexity_ask | 2 | 0 | 8887 | 0.00299
perplexity_chat | 2 | 0 | 10716 | 0.00276
```

The one unknown-cost call is the cancelled research run, which reports no usage. The research row
holds both research runs: a run is recorded under the tool that started it, whichever
`perplexity_jobs` call observed it. The two research costs add up to $0.01722 because only the
completed run had a known cost.

### `perplexity_projects`

Projects group what the server stores. A tool that stores something creates the project it names
the first time, and uses the project `default` when none is given; this tool only looks projects up
and never creates one. Project names are case-sensitive, 1 to 64 characters of ASCII letters, digits,
`-`, `_` and `.`, may not begin with `.`, and may not look like an API key.

| Argument | Type | Meaning |
|---|---|---|
| `action` | `list` or `delete` | Required. `list` shows all projects; `delete` removes one |
| `project` | string | Project name (`delete` only) |
| `confirm` | boolean | Must be `true` for `delete`; deletion cannot be undone |

Output: `action`; for `list`, `projects` (each with `name` and `created_at`, UTC); for `delete`,
`project`, `rows_removed`, `rows_retained` and `running_jobs`. `rows_removed` counts rows removed
from tables that reference the project directly (the project's chats and research jobs; the chat
messages go by cascade and are not counted). `running_jobs` counts the project's research jobs that
had not finished: deleting the project discards their local rows, so the spend of those runs is
never recorded while the provider keeps running and billing them. When it is above 0, the result
(and the `confirmation_required` message before it) carries a warning; cancel them first with
`perplexity_jobs cancel`.

**Deleting a project keeps its spend history.** Usage events are not deleted: each is detached from
the project (its project reference is cleared) and kept, together with the project's name as it was
written, so `perplexity_usage` still reports that spend under the deleted name. `rows_retained`
counts the events detached. Everything else stored in the project is removed. The project
`default` may be deleted; it is recreated the first time a tool stores records in it. A fresh
install lists no projects: `perplexity_ask`, `perplexity_research` and the first `send` of a new
chat create the project they name (or `default`); every other action only looks a project up.

```json
{"name": "perplexity_projects", "arguments": {"action": "list"}}
```

```json
{"action": "list", "projects": [{"name": "demo", "created_at": "2026-10-09T19:32:31Z"},
                                {"name": "research", "created_at": "2026-10-09T19:32:31Z"}],

 "project": null, "rows_removed": null, "rows_retained": null, "running_jobs": null}
```

Example, from the live acceptance run on 2026-10-09 (`d1.json` and `u3.json`): deleting the
project `acceptance`, which held 2 research jobs and 1 chat, then reporting its spend by name. The
delete result was recorded before `running_jobs` was added to it, so that key is not in the saved
file; the same call now also returns `"running_jobs": 0` for this project (both jobs had finished).

```json
{"name": "perplexity_projects", "arguments": {"action": "delete", "project": "acceptance", "confirm": true}}
```

```json
{"action": "delete", "projects": null, "project": "acceptance", "rows_removed": 3, "rows_retained": 6}
```

The spend of the deleted project is still there (`u3.json`, the same totals as before the delete):

```json
{"name": "perplexity_usage", "arguments": {"project": "acceptance", "group_by": "tool"}}
```

reports `totals.calls` 6 and `totals.cost_usd` `"0.02297"`, with the three tools as groups.

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
| `perplexity.db` | The SQLite database: projects, usage events, chats and their messages, research jobs with their queries and results (WAL mode, so `perplexity.db-wal` and `perplexity.db-shm` appear while it is open) |
| `migrate.lock` | Lock file so two processes starting together cannot migrate at once |
| `backup-<rev>.db` | Copy of the database as it was at schema revision `<rev>`, taken automatically before a migration touches a database that already has a revision (for example `backup-0001.db`, or `backup-0002.db` when a revision-0002 database starts on this release) |

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

**Downgrading also drops chats and research jobs.** Revision `0003` creates `chats` and
`chat_messages`, and revision `0004` creates `research_jobs`. A downgrade of `0004` (migration code
only) drops `research_jobs` with every job row, its stored queries and answers; a downgrade of
`0003` drops `chats` and `chat_messages` with every stored conversation. Each downgrade first
writes the backup named for the revision being left (`backup-0004.db` or `backup-0003.db`), and
that file holds the table and its rows: restoring it with the steps above brings them back. The
upgrade backup of a database that was at `0002` is `backup-0002.db`, which holds none of these
tables. A database that has just been created holds no chats or jobs, and a run that was already
started at the provider keeps running whatever happens to its row.

Use your own `PERPLEXITY_DATA_DIR` in the paths if you set one. Both server processes (a pm2 HTTP
instance and a stdio instance) may share one data directory.

## Development

```bash
uv sync                              # install runtime and dev dependencies from uv.lock
uv run pytest                        # offline test suite (about 60 s)
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
  client.py       the one Perplexity HTTP client (httpx2): retry, typed errors, redaction; the
                  Agent calls create_run, get_run and cancel_run
  errors.py       PerplexityError and the eleven error categories
  catalog.py      model list cache, stale-on-failure rule, documented presets
  agent.py        Agent API request building and validation, response digestion, run_costed
                  (the costed-call sequence) and the research job observation
  models/         tolerant pydantic models for API payloads (agent.py: Agent runs)
  tools/          one module per tool, each with register(server): ask, chat, research, jobs,
                  models, projects, usage
  usage.py        usage recorder (record_usage), money helpers, the Agent usage parser
  pricing.py      documented Perplexity prices in nano-USD, for costs the API does not report
  usage_report.py read-only spend report behind perplexity_usage
  storage/        engine, unit_of_work session, migration runner, project rules, ORM models,
                  chats.py (chat rows and history), jobs.py (research job rows)
  migrations/     Alembic environment and versions/NNNN_slug.py (packaged in the wheel)
  log_setup.py, redaction.py   stderr logging with secrets removed
tests/            offline tests, fixtures/, and the live-marked capture helper
openspec/         the spec-driven change records (py-foundation, py-usage-log, py-agent-api)
```

Contributor and agent guidance is in `CLAUDE.md`.

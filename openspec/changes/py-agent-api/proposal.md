# Proposal

## Why

The server has no tool that answers a question. Perplexity retired the Sonar endpoints (`403 chat_completions_not_available`), the replacement is the Agent API (`POST /v1/agent`), and the 2.0.0 rewrite so far ships only `perplexity_models`, `perplexity_projects` and `perplexity_usage`. The usage recorder (`py-usage-log`, archived 2026-10-09) exists but no tool calls it, so `perplexity_usage` reports zero. This change adds the Agent API toolset: a grounded one-shot `ask` that is cheap by default, a persisted `chat`, and long `research` as a background job with `jobs` management. It is also the first production caller of the recorder, so every costed call finally leaves a spend record.

The Agent API was probed live on 2026-10-09 (about $0.04 spent; 28 captures recorded as `tests/fixtures/agent_*.json`). The probe contradicted the documentation in several places that shape the design: `annotations` is always empty so citations cannot be mapped to sources, cancelling an unknown run returns the same misleading `400` as cancelling a finished one, a mixed allow/deny domain list and a malformed date are accepted although documented as invalid, `store:false` still persists server-side (only retrieval is hidden), and `created_at` / `completed_at` are rewritten on every GET. See `design.md` "Observed shapes".

## What Changes

- Add four tools, `perplexity_ask`, `perplexity_chat`, `perplexity_research` and `perplexity_jobs`, with typed parameters, output models and annotations like the existing tools. Depth is chosen by the caller (`fast`, `low`, `medium` synchronously; `medium`, `high`, `xhigh` only as a background run). There is no auto-routing and no cost ceiling in this version; defaults are the cheap ones and each tool description states approximate per-depth costs taken from the probe.
- `perplexity_ask`: synchronous, single turn, default depth `fast`, optional explicit model, search filters (domains, recency, dates, country, result count), instructions, output-token cap and structured output. The answer comes back with de-duplicated sources, the resolved model, status, a usage summary with an exact USD cost string, and latency.
- `perplexity_chat`: `send`, `list`, `read`, `delete` over a local chat history (new tables `chats` and `chat_messages`, migration `0003`). A turn continues from the previous response with `previous_response_id`; a `replay` option resends the stored history when that continuation fails.
- `perplexity_research`: starts a background run and returns a job id at once. `perplexity_jobs`: `list`, `status`, `result`, `cancel` over local job rows (new table `research_jobs`, migration `0004`). Nothing ever waits for a run to finish.
- Wire the usage recorder into every one of them in the order the recorder contract requires: exactly one usage event per costed call, none for a submit, a pending poll or a free call, and one for a background run at its first terminal observation.
- Extend the client with Agent API models and helpers (create, fetch, cancel) and a per-call read timeout setting `PERPLEXITY_AGENT_READ_TIMEOUT` (default 120 s) for synchronous runs.
- Validate locally what the probe showed the API accepts wrongly or reports misleadingly (empty query, mixed domain lists, date formats, `store:false` on a background run).
- Out of scope: streaming, the Search, Embeddings and Decisions APIs, profiles, skills, MCP connectors and sandbox tools, image attachments, auto-routing and cost ceilings, pruning of chats, jobs or events.

## Capabilities

### New Capabilities

- `agent-client`: typed access to the Agent API in the client: create, fetch and cancel a run, tolerant response models, the synchronous-run read timeout, retry rules and error mapping for the Agent endpoints.
- `agent-ask`: the `perplexity_ask` tool: depth, explicit model, search filters, structured output, the answer-and-sources result, incomplete answers, and recording of its usage.
- `agent-chat`: the `perplexity_chat` tool and its local chat storage, continuation and replay.
- `agent-research`: the `perplexity_research` and `perplexity_jobs` tools, the local job storage, terminal-state usage recording and cancellation.

### Modified Capabilities

- `server-runtime`: the configuration requirement gains `AGENT_READ_TIMEOUT` and its documented default.

## Impact

- **Code:** `src/mcp_perplexity_pro/` gains `models/agent.py`, `agent.py` (request building, validation, response digestion and the shared costed-call sequence), `tools/ask.py`, `tools/chat.py`, `tools/research.py`, `tools/jobs.py`, three ORM models in `storage/models.py` and migrations `0003_chats.py` and `0004_research_jobs.py`; `client.py` gains the three helpers and a per-call timeout; `settings.py` gains `agent_read_timeout`; `tools/__init__.py` registers four tools (seven in total).
- **Dependencies:** none new.
- **Settings:** `PERPLEXITY_AGENT_READ_TIMEOUT` (default 120).
- **Data:** three new tables, project-scoped with `ON DELETE CASCADE` (ordinary, not retained: deleting a project removes its chats and jobs, while spend history stays). Both migrations are reversible and take the pre-migration backup; a downgrade drops chats or jobs with their rows.
- **Spend:** this change makes the server capable of spending money. Defaults are the cheapest depths; `high` and `xhigh` exist only behind `perplexity_research`. The live acceptance task spends under $0.05 at the cheapest depths.
- **Tool surface:** from three tools to seven. The CLAUDE.md design target of about nine tools leaves room for the Search, Embeddings and Decisions tools only if later epics stay lean.
- **Fixtures:** `tests/fixtures/agent_*.json` (28 new captures from 2026-10-09, committed before this change in `82c747a`) define the models and every spec scenario.
- **Risks carried forward:** multi-level `store:false` continuation is verified for one level only (an apply-time live task checks more, with the replay fallback as the answer); `high` and `xhigh` costs are not measured here; a cancelled run reports no usage, so its cost is recorded as unknown (see design D9).

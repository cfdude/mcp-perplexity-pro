# Proposal

## Why

Every upstream Perplexity call now costs real money and the server keeps no record of it: the Agent API reports a per-call `usage` object (tokens, per-tool invocations, a USD cost breakdown; recorded in `tests/fixtures/agent_fast.json`), and the Search, Embeddings and Decisions APIs bill by documented price lists. Without a durable record there is no cost visibility, and the model-router epic that comes later has no feedback data (which model, preset and tool cost what, per project) to learn from. Four more epics are about to add tools that spend money (`py-agent-api`, `py-search-api`, `py-decisions-tool`, `py-embeddings`), so the recorder has to exist first, with its contract fixed, so each of them calls it instead of inventing its own.

## What Changes

- Add a `usage_events` table (migration `0002_usage_events.py`, reversible): one row per upstream call, capturing the full field set up front because the table accumulates external API data and cannot be reconstructed later (typed columns for the scalar token and cost fields, a normalized per-upstream-tool column, and the verbatim `usage` JSON).
- Add a best-effort recorder, `record_usage(...)`, that runs in its own short unit of work after the upstream call, records failed calls too (cost 0, status = error category), and can never fail or alter the tool call it observes. A parser, `usage_from_agent_response(...)`, turns an Agent `usage` object into the recorder's input.
- Add `pricing.py`: dated, source-cited documented prices (Search, Decisions, Embeddings, Agent tool and sandbox fees), used only when the API reports no cost, plus exact integer money handling (nano-USD) and a USD formatter.
- Add a read-only tool `perplexity_usage` reporting spend: totals plus one grouping (`tool`, `api`, `model`, `project` or `day`), filtered by project and UTC date range.
- **Amend `local-storage`**: spend history must outlive the project it was spent in, so project deletion now keeps "retained" tables (a foreign key to `projects` declared `ON DELETE SET NULL`) and detaches them instead of deleting them; the "every record belongs to a project" and "one unit of work per call" requirements gain the exceptions this needs.
- Out of scope: wiring the recorder into real tools. No existing tool makes a costed upstream call (`perplexity_models` lists models, which is free), so nothing is recorded in production until `py-agent-api` and the others land; this change proves the table, recorder, prices and report with a test-only caller. Also out of scope: pruning or exporting events (retention is "keep everything"; see design Non-Goals), budgets or spend limits, and token prices for Agent models (those arrive in the API response or from the live catalog).

## Capabilities

### New Capabilities

- `usage-recording`: the usage event table, the best-effort recorder and its failure isolation, exact money, cost sources and documented prices.
- `usage-reporting`: the read-only `perplexity_usage` tool.

### Modified Capabilities

- `local-storage`: project deletion keeps retained records (new requirement), and the project-resolution, project-management and all-or-nothing requirements are amended accordingly.

## Impact

- **Code:** `src/mcp_perplexity_pro/` gains `pricing.py`, `usage.py`, `tools/usage.py`, a `UsageEvent` model in `storage/models.py` and `migrations/versions/0002_usage_events.py`; `storage/projects.py` (`_scoped_tables`, `delete_project`) and `tools/projects.py` (result gains `rows_retained`) change; `tools/__init__.py` registers the new tool.
- **Dependencies:** none new.
- **Settings:** none new (no on/off switch for recording; see design D12).
- **Data:** one new table; the 0001 to 0002 upgrade takes the automatic pre-migration backup; downgrade drops `usage_events` and its rows.
- **Tool surface:** `perplexity_usage` is the third tool; `perplexity_projects delete` reports an extra count and no longer deletes spend history.
- **Risk carried forward:** only the Agent API has a recorded `usage` shape (fixtures); the Search, Decisions and Embeddings response shapes are not verified here, so this change defines the recorder input generically and leaves each of those parsers to its own epic, after probing the live API (`docs/lessons/docs-lie-probe-the-api-first.md`).

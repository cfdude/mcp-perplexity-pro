# Proposal

## Why

An agent that meets this server has ten tools, about 60 KB of schema and nothing that tells it, in one cheap read, which tool to pick, what a call costs, which calls are billed or asynchronous, or how to fix an error. The tool descriptions try to do all of that and are the largest part of `tools/list` (it grew from 56898 to 59779 bytes with the routing modes, and Rob accepted that growth on 2026-10-13 on the condition that this change is the lever that trims it). From the agent's side, what avoids wasted calls is: a decision table first, cost and latency up front, one copy-paste example per tool, a flag for every billed, asynchronous or destructive action, an error-to-fix table, and help that is cheap to fetch (an index under about 1.5 KB, details on demand). A CLI, planned next (`py-cli`), needs the same text behind `--help`, so it must come from one source.

## What Changes

- Add one tool, `perplexity_help`, with actions `index` (the default: an llms.txt-style markdown page with a decision table, every tool in one line and the topic list), `tool` (one tool: what it is for, billed or async or destructive flags, arguments generated from the live tool schema so they cannot drift, costs and latency, one example call, the result keys, the errors it raises and their fixes) and `topic` (`routing`, `costs`, `citations`, `errors`, `projects`). It is read-only, costs nothing, calls no API and records no usage.
- Keep the help text in one module (`help_text.py`) whose pure functions render the index, a tool and a topic. The MCP tool uses them now and the CLI's `--help` and `help <topic>` will use them (`py-cli`).
- Make errors self-teaching: an `invalid_request` from any tool other than help gets a trailing sentence naming the exact `perplexity_help` call that shows that tool's arguments. The category and the rest of the message do not change.
- Pay back the eleventh tool: trim the descriptions and the input and output schema field descriptions of the largest tools (`perplexity_chat`, `perplexity_jobs`, `perplexity_ask`, `perplexity_research`, `perplexity_embed`) down to what the specs require plus a pointer to help, and move the rest into help topics. Budget, pinned by a test: `tools/list` no larger than the 59779 bytes measured after the routing change, with the help tool included.
- Out of scope: the CLI itself (`py-cli`), an MCP resource or prompt for help (many clients never show them to the agent), generated per-tool pages on disk, translations.

## Capabilities

### New Capabilities

- `help-tool`: the `perplexity_help` tool, its three actions, the single source of the text, the size limits that keep it cheap, and the rule that every registered tool has a help entry.

### Modified Capabilities

- `server-runtime`: a new requirement that an `invalid_request` from a tool with a help entry names the help call for that tool.
- `routing-config`: "The instructions text" also names `perplexity_help`, and help is stated not to be a fifth channel of the configuration.

## Impact

- **Code:** new `help_text.py` (pure rendering), new `tools/help.py` (registration), `tools/__init__.py` (one more `register`), `server.py` (the error middleware adds the hint), and trimmed docstrings in `tools/ask.py`, `tools/chat.py`, `tools/jobs.py`, `tools/research.py`, `tools/embeddings.py`. No new dependency, no migration, no new setting.
- **Tests:** new `tests/test_help_text.py` and `tests/test_help_tool.py`; the tool-list assertions that name ten tools (`tests/test_server.py`, `tests/test_contract_checks.py`) gain the eleventh; description tests keep the spec-pinned statements (costs, retention wording).
- **Tool surface:** ten tools become eleven. CLAUDE.md says to prefer one tool with an `action` over several and to trim descriptions before adding a tool; this change does both (one tool with actions, and the trim is a task here).
- **Spend:** none. Live acceptance calls the help tool on the running server and spends nothing.

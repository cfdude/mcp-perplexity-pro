## Context

From the agent's side the missing thing is orientation: which tool, what it costs, which calls are billed or asynchronous, how to fix an error. Today that is spread across ten long descriptions. Rob asked for a help tool (verbs like listing tools and getting one tool's help, or an llms.txt-style markdown page, "whatever works best") and a normal `--help` on the CLI, and for the agent's point of view to drive the content. `perplexity_models` already carries a routing section and the server `instructions` carry the routing mode; help is the general version for the rest.

## Goals / Non-Goals

**Goals:** one cheap call to the right tool; every claim in help generated from, or tested against, the code or the README so it cannot drift; the same text reusable by the CLI; the eleventh tool paid for by trimming descriptions.

**Non-Goals:** the CLI, an MCP resource or prompt (the clients that matter for agents show tools, not resources), documentation on disk, a search over help, translating.

## Decisions

**D1. One tool with an `action`.** `perplexity_help(action, name)`: `index` (default, no name), `tool` (`name` is a tool name), `topic` (`name` is a topic). Three verbs are the smallest set that matches how an agent asks: "what is here", "how do I call X", "explain Y". Rob's suggested `list-tools`/`get-tool-help` map to `index` and `tool`; the index also lists the tools, so the common first call needs no second.

**D2. llms.txt-style markdown, returned as the text and as `text` in the structured content.** Headings, short lines, a table for the decision. The structured result also carries `tools` and `topics` (the valid names) so a client can iterate without parsing markdown. No other schema fields (output schema bytes are the cost we are trying to cut).

**D3. The index is capped at 1500 bytes and always states the active routing mode.** A test pins the cap. Content, in order: one line of purpose; the decision table ("a quick fact: perplexity_ask; a report that takes minutes: perplexity_research then perplexity_jobs; links without an answer: perplexity_search; ..."); one line per tool with a cost class (free, billed, billed and async, destructive); the topic names; how to ask for more. Rejected: a long index (an agent stops calling help if it is large).

**D4. Arguments come from the live tool schema, the rest is curated.** `tool` output lists each parameter's name, readable type (optional unions and enums rendered as `string or null` and `fast, low or medium`), whether it is required and its schema description, read at call time from the registered tool (so a new parameter appears in help without an edit and cannot be stale). `help_text` takes plain data (a list of `{name, params, annotations}` dicts built by the tool wrapper), never FastMCP objects. Purpose, the example call, the top-level result keys per action (output schemas are unions across actions, so they are curated, not generated) and the errors are curated text in `help_text.py`; the billed, read-only and destructive flags are tested against each tool's annotations. A test fails if a registered tool has no curated entry, if an example call does not validate against that tool's input schema (jsonschema), or if a result key named in help is not a top-level property of the output schema.

**D5. Costs in help name their sample.** The `costs` topic and each tool entry quote only the README's measured figures (the descriptions keep the rounded ranges their specs pin, which contain the measured ones; the two forms are not reconciled here) ("observed N runs, range X to Y") and a test checks that every dollar figure in help also appears in the README, so the two cannot disagree (docs/lessons/a-measurement-in-docs-names-its-sample.md).

**D6. Single source for the CLI.** `help_text.py` exposes pure functions (`render_index(settings, tools)`, `render_tool(name, settings, schema)`, `render_topic(name, settings)`, `TOPICS`) with no FastMCP import, so `py-cli` prints the same text for `--help` and `help <topic>`. The MCP tool is a thin wrapper that reads schemas from the registered tools.

**D7. Errors point at help, narrowly.** For a failure with category `invalid_request` raised by a tool that has a help entry other than `perplexity_help`, `ErrorContractMiddleware` appends one sentence: `Call perplexity_help with action "tool" and name "<tool>" for its arguments and examples.` The structured `message` and the text carry the same sentence; the category and every other byte are unchanged. Not added to other categories (they are not an agent mistake about arguments) and not to help's own errors (they already list the valid names). FastMCP argument-validation errors take the same path.

**D8. The trim has a budget and a test.** Measured 2026-10-13 on the live server: the five descriptions total about 5.2 KB and much of that is pinned by specs and tests (per-depth costs, the retention wording, "never waits for a background run", "web search tool alone", "SENDS the text", "never create a project", the routing sentence), so a description-only trim saves about 1.5 to 2 KB while the help tool itself costs about 3 KB. Most of `tools/list` is schema field descriptions (chat about 13.7 KB, jobs about 9.6 KB, embed about 7 KB), so the levers are the descriptions and the input and output field descriptions of the largest tools, shortened to a few words with the detail moved into help. A test builds the server and fails if `tools/list` exceeds 59779 bytes. The lever that did the work is not prose: pydantic writes a `title` annotation on every schema node (it only repeats the property name), and a middleware (`CompactSchemasMiddleware`) now strips those from every input and output schema in `tools/list` (about 14% of the schema bytes; a property that is itself named `title` stays). The descriptions only gain the closing pointer; their pinned statements are untouched. If the budget cannot be met without dropping a pinned statement, the spec's number is amended before Gate 2 to the achieved size and Rob is told (he accepted the routing growth on that condition).

**D9. No usage, no project, no network.** The tool opens no unit of work and never creates a project; it has `readOnlyHint` true and `openWorldHint` false.

## Risks / Trade-offs

- **An eleventh tool costs bytes in every session** (D8 repays it; measured at apply).
- **Curated text drifts** (D4, D5: generated arguments, example validation, README figure check; the remaining prose is covered by review at Gate 2 and the docs review).
- **Agents may never call help.** The routing `instructions` text (modified by this change) and every `invalid_request` from a tool with a help entry point at it (D7); the index is small enough to be worth calling.
- **The hint lengthens error messages by about 100 bytes**; only `invalid_request`, the one category an agent can fix by reading help.

## Migration Plan

No database, setting or API change. A client that lists tools sees one more.

## Open Questions

None blocking.

## ADDED Requirements

### Requirement: Help tool
The server SHALL provide `perplexity_help`, a read-only tool with an `action` of `index` (the default), `tool` or `topic` and an optional `name`. It SHALL call no API, record no usage, open no database unit of work and create no project, and SHALL advertise `readOnlyHint` true, `destructiveHint` false and `openWorldHint` false. Its result SHALL carry the markdown `text` and the valid `tools` and `topics` names.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_help` is present with typed parameters, an output schema and the three annotations above

#### Scenario: A help call costs nothing
- **WHEN** a client calls `perplexity_help` in any action
- **THEN** no request reaches the API, no usage event is written and no project exists afterwards

### Requirement: The index is small and decides
`action` `index` SHALL return markdown of at most 1500 bytes holding: one line of purpose, the active routing mode, a decision table that maps a need to a tool, one line per registered tool with whether it is free, billed, billed and asynchronous or destructive, the topic names and how to ask for more.

#### Scenario: Index content
- **WHEN** a client calls `perplexity_help` with no arguments
- **THEN** the text names every registered tool exactly once in its tool list, names the five topics, states the routing mode and is at most 1500 bytes

#### Scenario: The decision table
- **WHEN** a client reads the index
- **THEN** it maps a quick grounded fact to `perplexity_ask`, a long report to `perplexity_research` with `perplexity_jobs`, links without an answer to `perplexity_search`, and a local history to `perplexity_chat`

### Requirement: Tool help
`action` `tool` with a tool `name` SHALL return markdown stating what the tool is for, whether a call is billed, asynchronous or destructive, one line of costs and latency, one copy-paste example call, its arguments (name, type, required or not, description) read from the registered tool's input schema, the result keys read from its output schema, and the errors it raises with the fix for each. A missing or unknown `name` SHALL fail with `invalid_request` listing every valid tool name.

#### Scenario: Arguments cannot drift
- **WHEN** a parameter is added to a registered tool
- **THEN** `perplexity_help` `tool` for it lists that parameter without any edit to the help text

#### Scenario: Unknown tool
- **WHEN** a client asks for `name` `perplexity_ask2`
- **THEN** the call fails with `invalid_request` naming `name` and listing the valid tool names

### Requirement: Topic help
`action` `topic` SHALL accept `routing`, `costs`, `citations`, `errors` and `projects` and return at most 3000 bytes of markdown for it. The `costs` topic SHALL name how many runs and which query shape stand behind each figure, and every dollar figure in help SHALL also appear in the README. A missing or unknown `name` SHALL fail with `invalid_request` listing the topics.

#### Scenario: Costs name their samples
- **WHEN** a client asks for topic `costs`
- **THEN** each figure carries the number of observations or the words "one sample", and the text says the default model's cost differs from the per-depth figures

#### Scenario: Unknown topic
- **WHEN** a client asks for topic `pricing`
- **THEN** the call fails with `invalid_request` naming `name` and listing the five topics

### Requirement: One source, covered by tests
The help text SHALL be rendered by pure functions that import neither FastMCP nor the database, so the CLI can print the same text. Every registered tool SHALL have a curated help entry, every example call SHALL validate against its tool's input schema, and every result key a help entry names SHALL exist in the tool's output schema.

#### Scenario: A tool without help
- **WHEN** a tool is registered that has no curated help entry
- **THEN** the test suite fails naming the tool

#### Scenario: A broken example
- **WHEN** an example call names an argument the tool does not have
- **THEN** the test suite fails naming the tool and the argument

### Requirement: Descriptions defer to help
The descriptions of `perplexity_ask`, `perplexity_chat`, `perplexity_research`, `perplexity_jobs` and `perplexity_embed` SHALL keep every statement their own specs require and end with a sentence pointing at `perplexity_help`, and the `tools/list` response with the help tool included SHALL be no larger than 59779 bytes (the size measured after the routing modes), or the acceptance record SHALL state the shortfall.

#### Scenario: Pointer present
- **WHEN** a client lists the tools
- **THEN** each of the five descriptions ends with a pointer to `perplexity_help`

#### Scenario: Pinned statements survive
- **WHEN** the descriptions are trimmed
- **THEN** the per-depth costs, the retention wording and the no-upstream-call statements that other specs require are still present

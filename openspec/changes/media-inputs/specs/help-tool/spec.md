# help-tool Specification

## MODIFIED Requirements

### Requirement: The index is small and decides
`action` `index` SHALL return ASCII markdown of at most 1500 bytes holding: one line of purpose, the active routing mode, a decision table that maps a need to a tool, one line per registered tool with whether it is free, billed, billed and asynchronous or destructive, the topic names and how to ask for more.

#### Scenario: Index content
- **WHEN** a client calls `perplexity_help` with no arguments
- **THEN** the text names every registered tool exactly once in its tool-list section (the decision table may name them again), names the six topics, states the routing mode and is at most 1500 bytes, all ASCII

#### Scenario: The decision table
- **WHEN** a client reads the index
- **THEN** it maps a quick grounded fact to `perplexity_ask`, a long report to `perplexity_research` with `perplexity_jobs`, links without an answer to `perplexity_search`, and a local history to `perplexity_chat`

### Requirement: The tools list has a size budget
The `tools/list` response with the help tool included SHALL be no larger than 59779 bytes and a test SHALL fail above that budget. The cap SHALL NOT be raised: if the final measurement of a release cannot fit, work stops and the owner is asked. The levers are the closing pointers, shorter descriptions and the removal of the `title` annotations pydantic writes on every schema node.

#### Scenario: The budget holds
- **WHEN** the server is built and its tools listed, for the default, the dynamic and the dynamic-with-Decisions variants
- **THEN** the JSON size of the list is at most 59779 bytes for each

#### Scenario: Media growth is bounded
- **WHEN** the figures are measured at the commit `media-inputs` starts from and in its task 3.3 (after the parameters of both changes have landed)
- **THEN** the gross schema growth from `attachments` and the models inputs is at most 900 bytes per variant, a trim of at least 300 bytes from descriptions has landed besides the trim that `routing-v2` makes, and the recorded combined table fits every variant

#### Scenario: Nothing fits
- **WHEN** the final measure exceeds 59779 for any variant after both trims
- **THEN** the cap is not raised; the work stops and the owner decides what to cut


### Requirement: Topic help
`action` `topic` SHALL accept `routing`, `costs`, `citations`, `errors`, `projects` and `attachments` and return at most 3000 bytes of markdown for it. The `costs` topic SHALL name how many runs and which query shape stand behind each figure, and every dollar figure in help SHALL also appear in the README (help quotes the README's measured ranges; the descriptions keep the rounded ranges their specs pin). A missing or unknown `name` SHALL fail with `invalid_request` listing the topics.

#### Scenario: Costs name their samples
- **WHEN** a client asks for topic `costs`
- **THEN** each figure carries the number of observations or the words "one sample", and the text says the default model's cost differs from the per-depth figures

#### Scenario: Routing topic
- **WHEN** a client asks for topic `routing` on a `standard` and on a `custom` server
- **THEN** the text states the mode, the default model (standard) or the three tier ids (custom), that an explicit `model` always wins, and that two of `depth`, `tier` and `model` cannot be combined

#### Scenario: Errors topic
- **WHEN** a client asks for topic `errors`
- **THEN** the text lists every category of the closed vocabulary with what to do about it, and a test fails if a category is added without being listed

#### Scenario: Citations topic
- **WHEN** a client asks for topic `citations`
- **THEN** the text says sources are what the run touched and not a citation of each claim, and that an answer marker `[N]` or `[web:N]` matches a source's `ids`

#### Scenario: Projects topic
- **WHEN** a client asks for topic `projects`
- **THEN** the text says every stored record belongs to a project, that a project is created by the first costed call that stores something, and that deleting a project keeps the spend history

#### Scenario: Attachments topic
- **WHEN** a client asks for topic `attachments`
- **THEN** the text names the three forms, the supported types and the limits, and `perplexity_help` `topic` with an unknown name lists `routing`, `costs`, `citations`, `errors`, `projects` and `attachments`

#### Scenario: Unknown topic
- **WHEN** a client asks for topic `pricing`
- **THEN** the call fails with `invalid_request` naming `name` and listing the six topics

## ADDED Requirements

### Requirement: An attachments topic
The `attachments` topic (also rendered by `perplexity-pro help attachments`) SHALL state the three forms of an attachment, the supported and unsupported types (audio and video), the limits (10 items, 20 MiB per file, 32 MiB per call, 1 MiB inline, 30 documents per chat) and one runnable example per tool, and the index SHALL list it.

#### Scenario: The topic renders
- **WHEN** a client calls `perplexity_help` with action `topic` and `name` `attachments`
- **THEN** the text names the three forms, the supported types and the limits

#### Scenario: The index lists it
- **WHEN** a client calls `perplexity_help` with action `index`
- **THEN** `attachments` is among the topics

### Requirement: The attachments topic explains handling and storage
The topic SHALL say that files are read by the server and sent as base64, that URLs are passed to the provider, that file bytes are never stored (only a note of name, type, size and a short digest), what a follow-up and a replay do, the model gate and `perplexity_models` inputs, and that attachments can raise the cost. The ask and chat help entries SHALL mention `attachments` in at most one line each.

#### Scenario: Storage rule stated
- **WHEN** a client asks for the topic
- **THEN** the text says file bytes are never stored and that a replay does not resend files

### Requirement: Attachment help is covered by the help tests
Every example in the topic SHALL validate against its tool's input schema, and every dollar figure in the topic SHALL also appear in `README.md`.

#### Scenario: Examples validate
- **WHEN** the help tests run
- **THEN** each example validates against the schema of the tool it names, and every dollar figure appears in `README.md`

### Requirement: The errors topic describes the local rate limit
The `errors` topic and the README's error table SHALL say that `rate_limited` also covers the local wait for attachment bytes, and that no Retry-After applies to it.

#### Scenario: Errors topic
- **WHEN** a client asks for topic `errors`
- **THEN** the `rate_limited` entry mentions the local attachment wait and does not promise a Retry-After for it

# usage-recording Specification

## Purpose

Defines the durable record of what each upstream Perplexity call cost: which fields an event carries, how money is stored and sourced, which documented prices fill in when the API reports no cost, and the guarantee that recording never disturbs the tool call it observes. It is the feedback data for cost visibility and for later model routing.

## ADDED Requirements

### Requirement: One event per costed upstream call
For every upstream Perplexity API call a tool makes that can incur a charge, the server SHALL durably record exactly one usage event in the local database, whether the call succeeds or fails. Calls that are free to make, such as listing models, record nothing.

#### Scenario: Successful call
- **WHEN** a tool makes one upstream call that succeeds
- **THEN** exactly one usage event exists for it with status `ok`

#### Scenario: Failed call
- **WHEN** a tool's upstream call fails with category `rate_limited`
- **THEN** one usage event exists with status `rate_limited`, cost 0 and cost source `none`, and the tool still returns its error

#### Scenario: Two upstream calls
- **WHEN** one tool call makes two upstream calls
- **THEN** two usage events exist, one per upstream call

#### Scenario: Free call records nothing
- **WHEN** a client calls `perplexity_models`
- **THEN** no usage event is created

### Requirement: A response is recorded once
A successful upstream response with a request id SHALL yield at most one event for its API family, however many times it is recorded, because a background Agent run keeps one response id across its submit and every poll and carries usage only once it completes. A second record of the same response SHALL be ignored without error.

#### Scenario: Polled twice
- **WHEN** the completed background response with id `resp_caf1d3f9-3489-4a09-a6d8-3aafd929e535` is recorded twice
- **THEN** one event exists for it

### Requirement: Event identity fields
Each event SHALL carry the UTC time it was recorded, the MCP tool name, the API family (`agent`, `search`, `embeddings` or `decisions`), the resolved model and the requested preset when known, the upstream request or response id when given, a status (`ok` or the error category), the call latency in milliseconds, and the project it was made for (a reference and the project's name at that time) or none.

#### Scenario: Preset and resolved model both kept
- **WHEN** an Agent call requested preset `fast` and the response named model `openai/gpt-6-luna`
- **THEN** the event holds preset `fast` and model `openai/gpt-6-luna`

#### Scenario: Unknown family refused
- **WHEN** a caller records an event with an API family outside the four values
- **THEN** no event is stored and the problem is logged, without raising

#### Scenario: Call without a project
- **WHEN** a tool that takes no project makes a costed call
- **THEN** the event has no project reference and no project name

### Requirement: Reported usage kept in full
Each event SHALL carry every scalar the API reported: input, output, total, cached, cache-creation, cache-read and reasoning token counts; the cost breakdown (input, output, cache-read, cache-creation and upstream-tool costs); the currency; and, per upstream tool the API names, the invocation count and cost. It SHALL also keep the complete `usage` object exactly as received. A figure the API did not report is stored as unknown, not as 0.

#### Scenario: Recorded Agent response
- **WHEN** the recorded Agent response with 3426 input tokens, 1643 cache-creation tokens and one `search_web` invocation costing 0.001 USD is recorded
- **THEN** the event holds those token counts, the `search_web` invocation count 1 and cost, and a verbatim copy of the usage object

#### Scenario: Unreported figure
- **WHEN** an API response omits `cache_creation_cost`
- **THEN** that field is unknown on the event, not 0

#### Scenario: Unknown fields survive
- **WHEN** a usage object contains a field this server does not know
- **THEN** the field is present in the stored verbatim copy

### Requirement: Exact integer money
The server SHALL store every cost as a whole number of nano-USD (one billionth of a US dollar). A reported decimal cost SHALL be converted from its decimal text, rounding half up, so binary floating-point error never enters stored values, and totals SHALL be integer sums.

#### Scenario: Reported cost converted
- **WHEN** a response reports a cost of 0.00021 USD
- **THEN** the stored cost is 210000 nano-USD

#### Scenario: Sum is exact
- **WHEN** ten events each cost 0.00021 USD
- **THEN** their total is exactly 2100000 nano-USD

#### Scenario: Unusable cost
- **WHEN** a response reports a negative, non-numeric or non-USD cost
- **THEN** the event stores cost 0 with cost source `none`, keeps the verbatim usage object, and logs the problem

### Requirement: Cost source
Each event SHALL state where its cost came from: `reported` when the API gave a total cost (including 0), `computed` when the server derived it from the documented prices because the API reported none, or `none` when no cost is known, as for a failed call. A reported cost SHALL never be replaced by a computed one.

#### Scenario: Reported wins
- **WHEN** an Agent response reports a total cost and the server could also compute one
- **THEN** the event stores the reported total with source `reported`

#### Scenario: Computed from documented price
- **WHEN** a fast Search request reports no cost
- **THEN** the event stores 1000000 nano-USD with source `computed`

#### Scenario: Nothing to compute from
- **WHEN** an Embeddings call names a model absent from the documented prices and the API reports no cost
- **THEN** the event stores cost 0 with source `none`

### Requirement: Documented prices
The server SHALL hold Perplexity's documented prices as dated constants with their source address: Search per 1,000 requests (standard and fast), Decisions per million input tokens, Embeddings per million tokens for each documented model, and Agent upstream-tool fees and the sandbox session fee. Prices SHALL be used only to compute a cost the API did not report, and a computed event SHALL record the date of the price table used.

#### Scenario: Prices match the documentation
- **WHEN** the constants are compared with the documented pricing page captured on the table's date
- **THEN** every price equals the documented one

#### Scenario: Computed event names its table
- **WHEN** an event has cost source `computed`
- **THEN** it records the date of the price table used

### Requirement: Recording never disturbs the call
Recording SHALL never raise into, delay beyond the database busy timeout, or change the result of the tool call it observes. It SHALL run after the upstream call has returned or failed, in its own unit of work separate from any the tool uses, and SHALL NOT create projects. If recording fails, the failure SHALL be logged with secrets removed.

#### Scenario: Database unavailable
- **WHEN** the database is locked past the busy timeout when an event is recorded
- **THEN** the tool still returns its normal result, no exception reaches the client, and a redacted error is logged

#### Scenario: Tool's own writes roll back
- **WHEN** a tool makes a costed call and then fails after writing its own records
- **THEN** the tool's records are gone and the usage event for the call remains

#### Scenario: Project not created
- **WHEN** an event is recorded naming a project that no longer exists
- **THEN** the event is stored with no project reference and the given project name, and no project is created

#### Scenario: Caller cancelled
- **WHEN** the calling tool task is cancelled while the event is being written
- **THEN** the event is still written

### Requirement: No content stored
An event SHALL NOT contain prompts, response text, request bodies, headers or the API key. Text fields SHALL have key-shaped tokens removed before storage.

#### Scenario: Key-shaped text
- **WHEN** an event is recorded whose request id contains a key-shaped token
- **THEN** the stored value contains no such token

#### Scenario: Only usage stored
- **WHEN** an Agent response is recorded
- **THEN** no part of its output text or the request prompt is stored

### Requirement: Spend history is retained
Usage events SHALL survive deletion of their project, keeping the project name, and SHALL NOT be deleted or altered automatically; this change provides no pruning.

#### Scenario: Project deleted
- **WHEN** a project that has usage events is deleted
- **THEN** its events remain with no project reference and the original project name

#### Scenario: Same name recreated
- **WHEN** a project with the same name is created after deletion
- **THEN** the old events keep no project reference and are still reported under that name

### Requirement: Usage table migration
The usage table SHALL be created by a reversible migration with a four-digit sequence prefix that follows the existing one. Upgrading SHALL keep existing projects, and downgrading SHALL restore the previous schema with projects intact.

#### Scenario: Upgrade from the initial schema
- **WHEN** a database holding projects at the previous revision is upgraded
- **THEN** the projects are unchanged and the usage table exists and is empty

#### Scenario: Downgrade
- **WHEN** the usage migration is reversed
- **THEN** the usage table is gone and the projects table and its rows are intact

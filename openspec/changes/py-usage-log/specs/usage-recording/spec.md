# usage-recording Specification

## Purpose

Defines the durable record of what each upstream Perplexity call cost: which fields an event carries, how money is stored and sourced, which documented prices fill in when the API reports no cost, and the guarantee that recording never disturbs the tool call it observes. It is the feedback data for cost visibility and for later model routing.

## ADDED Requirements

### Requirement: One event per costed upstream call
For every costed upstream Perplexity API call that returns or fails with a categorized error, the calling tool SHALL invoke the recorder exactly once and the recorder SHALL store one usage event unless recording itself fails (best effort). A call retried by the client is one call. A background run is one call, recorded at its terminal response. A call cancelled before it returns is not recorded (accepted gap). Free calls, such as listing models, record nothing.

#### Scenario: Successful call
- **WHEN** a tool makes one upstream call that succeeds and invokes the recorder
- **THEN** exactly one usage event exists for it with status `ok`

#### Scenario: Failed call
- **WHEN** a tool's upstream call fails with category `rate_limited`
- **THEN** one usage event exists with status `rate_limited`, cost 0 and cost source `none`, and the tool still returns its error

#### Scenario: Two upstream calls
- **WHEN** one tool call makes two upstream calls that return distinct billed responses
- **THEN** two usage events exist, one per upstream call

#### Scenario: Free call records nothing
- **WHEN** a client calls `perplexity_models`
- **THEN** no usage event is created

#### Scenario: Cancelled before the upstream call returns
- **WHEN** the tool task is cancelled while its upstream call is still in flight
- **THEN** no usage event is created for that call

### Requirement: Recording order
A tool SHALL invoke the recorder only after its upstream call has returned or failed and while it holds no write unit of work on that engine, and SHALL NOT hold a write unit of work open across an upstream call. The sequence is: validate the project name, resolve the project in a unit that has committed, make the upstream call, record, then run the tool's own write unit.

#### Scenario: Recorder inside an open write unit
- **WHEN** the recorder is invoked while the caller's write unit of work is still open
- **THEN** it returns false within the busy timeout, stores nothing and logs a redacted error, and the tool's own write still commits

#### Scenario: Correct order
- **WHEN** a test-only tool follows the sequence for a costed call and then writes its own record
- **THEN** the usage event and the tool's record are both stored

### Requirement: A response is recorded once
A successful upstream response with a request id SHALL yield at most one event for its API family, however many times it is recorded, because a background Agent run keeps one response id across its submit and every poll and carries usage only once it completes. A second record of the same response SHALL be ignored without error. A submit or pending response SHALL NOT be recorded as `ok`.

#### Scenario: Polled twice
- **WHEN** the completed background response with id `resp_caf1d3f9-3489-4a09-a6d8-3aafd929e535` is recorded twice
- **THEN** one event exists for it

### Requirement: Event identity fields
Each event SHALL carry the UTC time it was recorded, the MCP tool name, the API family (`agent`, `search`, `embeddings` or `decisions`), the resolved model and the requested preset when known, the upstream request or response id when given, a status, the call latency in milliseconds, and the project it was made for (a reference and the project's name at that time) or none. The status SHALL be `ok` or a category of the server's closed error vocabulary.

#### Scenario: Preset and resolved model both kept
- **WHEN** an Agent call requested preset `fast` and the response named model `openai/gpt-6-luna`
- **THEN** the event holds preset `fast` and model `openai/gpt-6-luna`

#### Scenario: Unknown family refused
- **WHEN** a caller records an event with an API family outside the four values
- **THEN** no event is stored and the problem is logged, without raising

#### Scenario: Unknown status refused
- **WHEN** a caller records an event with a status that is neither `ok` nor an error category
- **THEN** no event is stored and a redacted problem is logged, without raising

#### Scenario: Call without a project
- **WHEN** a tool that takes no project makes a costed call
- **THEN** the event has no project reference and no project name

### Requirement: Outcome of an unsuccessful 200 response
A response that arrives with HTTP success but whose body reports a failed or incomplete run SHALL be recorded with status `unexpected_response`, keeping any usage it reports under the usual cost rules. No fixture shows what such a run bills, so the reported usage is kept rather than discarded or invented.

#### Scenario: Failed run with usage
- **WHEN** a terminal response with status `failed` carries a usage object reporting a total cost
- **THEN** the event has status `unexpected_response` and the reported cost with source `reported`

#### Scenario: Pending response not recorded as ok
- **WHEN** the caller holds a submit response with status `queued` and `usage` null
- **THEN** the caller does not record it, and nothing is stored with that response id

### Requirement: Reported usage kept in full
Each event SHALL carry every scalar the API reported: input, output, total, cached, cache-creation, cache-read and reasoning token counts; the cost breakdown (input, output, cache-read, cache-creation and upstream-tool costs); the currency; and, per upstream tool the API names, the invocation count and cost. It SHALL also keep the complete `usage` object as received, apart from the removals the sanitizing requirement states. A figure the API did not report is stored as unknown, not as 0.

#### Scenario: Recorded Agent response
- **WHEN** the recorded Agent response with 3426 input tokens, 1643 cache-creation tokens and one `search_web` invocation costing 0.001 USD is recorded
- **THEN** the event holds those token counts, the `search_web` invocation count 1 and cost, and a copy of the usage object equal to the original

#### Scenario: Unreported figure
- **WHEN** an API response omits `cache_creation_cost`
- **THEN** that field is unknown on the event, not 0

#### Scenario: Unknown fields survive
- **WHEN** a usage object contains a field this server does not know
- **THEN** the field is present in the stored copy

### Requirement: Parsing never fails
The recorder SHALL accept a usage object either already parsed or as the raw mapping and, for a raw mapping, parse it inside its own guarded block, so a parser fault never reaches the calling tool. Parsing SHALL never raise. Any malformed part (a non-mapping detail object, a string, negative, boolean or out-of-range token count, a non-mapping per-tool entry) SHALL become unknown for that figure and be logged, while every well-formed figure is kept.

#### Scenario: Malformed sub-fields
- **WHEN** a usage object has `input_tokens_details` as a list, `output_tokens` as `"30"`, `total_tokens` as -1 and a `tool_calls_details` entry that is a string
- **THEN** parsing returns normally, those figures are unknown, the other figures are kept and each problem is logged

#### Scenario: Out-of-range count
- **WHEN** a token count is `true` or exceeds 10^12
- **THEN** that count is unknown and the event is still stored

#### Scenario: Parser fault contained
- **WHEN** the recorder is handed a raw usage mapping and the parser raises
- **THEN** the recorder returns without raising, logs the fault redacted, and the tool's result is unchanged

### Requirement: Exact integer money
The server SHALL store every cost as a whole number of nano-USD (one billionth of a US dollar). A reported decimal cost SHALL be converted from its decimal text, rounding half up, so binary floating-point error never enters stored values, and totals SHALL be integer sums. A conversion that cannot complete, or a value above 10^12 nano-USD (1,000 USD) for one cost, SHALL be treated as unusable.

#### Scenario: Reported cost converted
- **WHEN** a response reports a cost of 0.00021 USD
- **THEN** the stored cost is 210000 nano-USD

#### Scenario: Sum is exact
- **WHEN** ten events each cost 0.00021 USD
- **THEN** their total is exactly 2100000 nano-USD

#### Scenario: Unusable cost
- **WHEN** a response reports a negative, non-numeric or non-USD cost
- **THEN** the event stores cost 0 with cost source `none`, keeps the usage object, and logs the problem

#### Scenario: Cost out of range
- **WHEN** a response reports a total cost of 1e30, or of 9.3e9 USD
- **THEN** the event is stored with cost 0 and source `none`, and no exception reaches the caller

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
Recording SHALL never raise into, delay beyond the database busy timeout, or change the result of the tool call it observes, including when parsing the usage it is handed fails. It SHALL run after the upstream call has returned or failed, in its own unit of work separate from any the tool uses, and SHALL NOT create projects. If recording fails, the failure SHALL be logged with secrets removed.

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

### Requirement: Stored usage JSON is sanitized and bounded
The stored usage JSON SHALL be the usage object serialized as strict JSON (no NaN or Infinity), with key-shaped tokens removed from the text, and at most 16 KB. An object that cannot be serialized strictly, whose redacted text no longer parses, or that exceeds the cap SHALL be replaced by a marker object naming the reason and, for size, the original byte count. The upstream-tool names, currency, model, preset, request id, tool and project name SHALL pass the same removal.

#### Scenario: Key-shaped value inside usage
- **WHEN** a usage object holds a key-shaped token in one field and ordinary values elsewhere
- **THEN** the stored copy has that token removed and, once parsed, every other field equals the original

#### Scenario: Non-finite number
- **WHEN** a usage object contains NaN
- **THEN** the event is stored with the marker object in place of the copy and no exception is raised

#### Scenario: Redaction breaks the JSON
- **WHEN** a configured secret containing a quote is redacted from the serialized usage and the result no longer parses
- **THEN** the event is stored with the marker object and no exception is raised

#### Scenario: Oversize usage
- **WHEN** a serialized usage object is larger than 16 KB
- **THEN** the event is stored with the marker object carrying the original size, and the typed columns still hold the parsed figures

### Requirement: Spend history is retained
Usage events SHALL remain after their project is deleted and keep the project name; the detach of the project reference is owned by the `local-storage` retained-record rules. Events SHALL NOT be deleted or altered automatically, except by that detach or an explicit downgrade of the migration; this change provides no pruning.

#### Scenario: Project deleted
- **WHEN** a project that has usage events is deleted
- **THEN** its events remain with no project reference and the original project name, and reports find them by that name

#### Scenario: Same name recreated
- **WHEN** a project with the same name is created after deletion
- **THEN** the old events keep no project reference and are still reported under that name

### Requirement: Usage table migration
The usage table SHALL be created by a reversible migration with a four-digit sequence prefix that follows the existing one. Upgrading SHALL keep existing projects, and downgrading SHALL restore the previous schema with projects intact. The built wheel SHALL contain the migration.

#### Scenario: Upgrade from the initial schema
- **WHEN** a database holding projects at the previous revision is upgraded
- **THEN** the projects are unchanged and the usage table exists and is empty

#### Scenario: Downgrade
- **WHEN** the usage migration is reversed
- **THEN** the usage table is gone and the projects table and its rows are intact

#### Scenario: Wheel contains the migration
- **WHEN** the wheel is built and listed
- **THEN** it contains `0002_usage_events.py`

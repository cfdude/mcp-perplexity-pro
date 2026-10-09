# Spec Delta

## Purpose

Defines `perplexity_ask`, the synchronous single-turn grounded question tool built on the Agent API: how the caller picks depth or a model, narrows the search, asks for structured output, what the result contains, and that every call is recorded as spend.

## ADDED Requirements

### Requirement: Ask tool
The server SHALL provide `perplexity_ask`, a stateless synchronous tool that answers one `query` with web-grounded search. Its description SHALL state approximate costs per depth (fast about $0.001 to $0.002, low about $0.004 to $0.02, medium about $0.016 to $0.05) and that it never waits for a background run. It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` false and `openWorldHint` true.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_ask` is present with typed parameters, an output schema, and a description naming the three costs

#### Scenario: Result validates
- **WHEN** an ask succeeds
- **THEN** its structured content validates against the advertised output schema and its text content carries the answer

### Requirement: Query is required
A query that is empty, only whitespace or longer than 20000 characters SHALL fail with category `invalid_request` naming `query` before any upstream call, any project creation and any usage event. The limit is this server's own sanity cap, not a provider limit.

#### Scenario: Blank query
- **WHEN** a client calls the tool with query `"   "`
- **THEN** the call fails with `invalid_request`, no request reaches the API and no usage event or project is created

#### Scenario: Oversized query
- **WHEN** a client calls the tool with a query of 20001 characters
- **THEN** the call fails with `invalid_request` naming `query` and nothing is sent or recorded

### Requirement: Depth selects a preset
`depth` SHALL be `fast` (the default), `low` or `medium` and selects the API preset of that name. `high` and `xhigh` SHALL be refused with `invalid_request` pointing to `perplexity_research`, because a run at those depths can last minutes and cost dollars.

#### Scenario: Default depth
- **WHEN** a client asks with no depth and no model
- **THEN** the request sent to the API names preset `fast`

#### Scenario: Medium depth
- **WHEN** a client asks with depth `medium`
- **THEN** the request names preset `medium`

#### Scenario: High depth refused
- **WHEN** a client asks with depth `high`
- **THEN** the call fails with `invalid_request` naming `perplexity_research` and no request reaches the API

### Requirement: Explicit model
An explicit `model` SHALL replace the preset: the request names the model and no preset, grounds it with the web search tool and a step budget of 3, unless `search` is false, which sends no tools. `depth` together with `model` SHALL fail with `invalid_request`, and so SHALL `search` false without `model`, because a preset always searches. `search` true is always accepted.

#### Scenario: Model with search
- **WHEN** a client asks with model `openai/gpt-6-luna`
- **THEN** the request names that model and no preset, carries one web search tool and a step budget of 3

#### Scenario: Model without search
- **WHEN** a client asks with that model and `search` false
- **THEN** the request carries no tools and the result's sources are empty

#### Scenario: Conflicting options
- **WHEN** a client passes `depth` `low` together with a model, or `search` false without a model
- **THEN** the call fails with `invalid_request` and no request reaches the API

#### Scenario: Search true is harmless
- **WHEN** a client passes `search` true with a depth and no model, or with a model
- **THEN** the request is the same as without `search`

### Requirement: Anthropic models get an output cap
When the model id begins with `anthropic/` and no `max_output_tokens` was given, the request SHALL carry a default cap of 4096 tokens, because the API rejects an Anthropic model without one.

#### Scenario: Default cap
- **WHEN** a client asks with model `anthropic/claude-haiku-4-5` and no cap
- **THEN** the request carries `max_output_tokens` 4096

#### Scenario: Explicit cap kept
- **WHEN** the same call gives `max_output_tokens` 200
- **THEN** the request carries 200

### Requirement: Domain filters are validated locally
`domains` SHALL hold at most 20 non-empty entries without whitespace, either all allowed or all denied with a `-` prefix, and a list that mixes both SHALL fail with `invalid_request` naming `domains` before any upstream call, although the API accepts such a list while its documentation calls it invalid.

#### Scenario: Mixed domain list
- **WHEN** a client passes domains `["python.org", "-reddit.com"]`
- **THEN** the call fails with `invalid_request` naming `domains` and no request reaches the API

#### Scenario: Too many or empty entries
- **WHEN** a client passes 21 domains, or a list containing an empty string
- **THEN** the call fails with `invalid_request` naming `domains`

### Requirement: Other search options are validated locally
`recency` SHALL be one of `hour`, `day`, `week`, `month`, `year`; `after` and `before` strict `YYYY-MM-DD` dates with `after` not later than `before`; `country` two ASCII letters; `max_results` 1 to 50. Any search option with `search` false SHALL fail. Each failure is `invalid_request` naming the option, before any upstream call.

#### Scenario: Malformed date
- **WHEN** a client passes `after` `09/15/2026` or `2026-13-40`
- **THEN** the call fails with `invalid_request` naming `after`, although the API accepts a malformed date

#### Scenario: Dates out of order
- **WHEN** `after` is `2026-10-01` and `before` is `2026-09-01`
- **THEN** the call fails with `invalid_request`

#### Scenario: Bad recency and result count
- **WHEN** a client passes recency `fortnight`, or `max_results` 0
- **THEN** each call fails with `invalid_request` naming the option

#### Scenario: Filters without search
- **WHEN** a client passes `recency` `week` with a model and `search` false
- **THEN** the call fails with `invalid_request`

### Requirement: Search filters are sent as the web search tool's options
When any filter is given the request SHALL carry one web search tool: domains, recency and dates inside its `filters` (dates converted to `MM/DD/YYYY`), `country` as its `user_location`, and `max_results` beside them. With no filter and a preset the request SHALL carry no tools, so the preset's own search applies. An explicit tool list replaces the preset's own tools, so a filtered run uses web search alone.

#### Scenario: Filters on a preset
- **WHEN** a client asks at depth `fast` with domains `["python.org"]`, recency `month` and country `US`
- **THEN** the request's single tool is `web_search` with `search_domain_filter` and `search_recency_filter` inside `filters` and `user_location` `{"country": "US"}` beside them

#### Scenario: Denylist and date conversion
- **WHEN** a client passes domains `["-reddit.com", "-wikipedia.org"]`, `after` `2026-09-15` and `max_results` 5
- **THEN** the filters hold the denylist and `search_after_date_filter` `09/15/2026`, and `max_results` is 5

#### Scenario: No filters
- **WHEN** a client asks with no filters at depth `low`
- **THEN** the request has preset `low` and no `tools` member

#### Scenario: Description names the replacement
- **WHEN** a client lists the tools
- **THEN** the description of `perplexity_ask` says that giving a search filter makes the run use the web search tool alone, as the recorded low-depth run with an explicit `fetch_url` tool ran no search

### Requirement: Instructions and output cap
`instructions` (at most 10000 characters) and `max_output_tokens` (1 to 64000) SHALL be passed to the API unchanged when given and omitted otherwise. A value outside those bounds SHALL fail with `invalid_request` naming it, before any call; the bounds are this server's own caps, not provider limits.

#### Scenario: Passed through
- **WHEN** a client gives instructions `"Answer tersely."` and `max_output_tokens` 400
- **THEN** the request carries both values

#### Scenario: Out of bounds
- **WHEN** a client gives `max_output_tokens` 64001 or instructions of 10001 characters
- **THEN** the call fails with `invalid_request` naming the option and nothing is sent

### Requirement: Structured output
When `json_schema` is given (root `type` `object`), the request SHALL carry a `json_schema` response format named `answer` and no `strict` member. The result SHALL keep the API's raw JSON text as the answer and add the parsed value as `answer_json` when it parses, else null with a warning. A non-object root SHALL fail with `invalid_request` before any call; a schema the API rejects SHALL surface as `invalid_request` with the API's message and a hint naming `json_schema`.

#### Scenario: Structured answer
- **WHEN** a client passes a schema for `{city, population}` and the API returns the recorded structured response
- **THEN** the answer text is `{"city":"Paris","population":2050000}` and `answer_json` equals that object

#### Scenario: Root not an object
- **WHEN** a client passes a schema with root type `array`
- **THEN** the call fails with `invalid_request` and no request reaches the API

#### Scenario: API rejects the inner schema
- **WHEN** the API returns the recorded generic 400 for a schema with an invalid inner type
- **THEN** the call fails with `invalid_request` and the message names `json_schema`

#### Scenario: Answer is not JSON
- **WHEN** the model's answer text does not parse as JSON
- **THEN** `answer_json` is null and a warning says so, and the answer text is still returned

### Requirement: Nothing is retrievable afterwards
Ask requests SHALL set `store` false: a single-turn answer is never fetched again. This hides the response from retrieval only; the API documents that it still persists state, so the tool description SHALL NOT claim that nothing is retained.

#### Scenario: Store flag
- **WHEN** any ask reaches the API
- **THEN** the request has `store` false

#### Scenario: Description makes no retention claim
- **WHEN** a client lists the tools
- **THEN** the description of `perplexity_ask` does not say the provider keeps nothing or deletes the answer, and says that `store` false only hides the response from retrieval

### Requirement: Answer
The result SHALL hold the answer text (the text of the final `message` output item), the resolved model, the requested depth or null, the response id, `status` and `latency_ms`. Inline citation markers in the text are returned unchanged.

#### Scenario: Completed answer
- **WHEN** the API returns the recorded fast response with filters
- **THEN** the result's answer equals that response's final message text, its model is `openai/gpt-6-luna`, its depth is `fast` and its status is `completed`

### Requirement: Sources
`sources` SHALL list the pages the run found or fetched, from its search results and fetched pages, de-duplicated by URL in first-seen order, each with `url`, `title`, `date` when known and the API's result `id` when it has one. The tool SHALL NOT map inline markers such as `[1]` or `[web:1]` to sources: the API's `annotations` are always empty and the numbering of the markers is unverified.

#### Scenario: Search sources
- **WHEN** the API returns the recorded fast response with filters
- **THEN** `sources` holds its search results in order, each URL once

#### Scenario: Fetched page as a source
- **WHEN** the API returns the recorded low-depth response that fetched a URL and ran no search
- **THEN** `sources` holds the fetched page with no result id

#### Scenario: Repeated URL
- **WHEN** two search result items contain the same URL
- **THEN** it appears once, at its first position

### Requirement: Incomplete answers
A response with HTTP 200 and status `incomplete` SHALL be returned as a result, not an error, with `status` `incomplete`, the API's reason as `incomplete_reason`, a warning that the answer was cut short, and an empty answer when the run produced no text.

#### Scenario: Truncated by the output cap
- **WHEN** the API returns the recorded response that stopped at `max_output_tokens`
- **THEN** the result has status `incomplete`, `incomplete_reason` `max_output_tokens`, an empty answer and a warning, and the call does not fail

### Requirement: Statuses other than completed or incomplete
A response with HTTP 200 whose status is neither `completed` nor `incomplete`, or whose `error` is not null whatever the status, SHALL fail with `unexpected_response` naming the status. It is recorded by the usual rule: a terminal failure (`failed`, `cancelled`, an unknown status, a `completed` run with an error) as one event, a `queued` or `in_progress` one not at all.

#### Scenario: Failed run on HTTP 200
- **WHEN** the API answers an ask with status `failed` and an error object
- **THEN** the call fails with `unexpected_response` naming `failed` and one event exists with status `unexpected_response`

#### Scenario: Completed with an error
- **WHEN** the API answers with status `completed` and a non-null `error`
- **THEN** the call fails with `unexpected_response` and one event exists

#### Scenario: Still running
- **WHEN** the API answers a synchronous ask with status `in_progress`
- **THEN** the call fails with `unexpected_response` naming `in_progress` and no event exists

### Requirement: Upstream text is redacted and capped
Every string from the API that is returned or stored (a status shown verbatim, an incomplete reason, an error text, a warning built from one) SHALL have the configured key and key-shaped tokens removed, then be cut to 64 characters for a status, 200 for a reason and 2000 for an error text. The caller's query, instructions, messages and titles, the model's answer and the sources' titles and URLs are content, stored and returned as they are.

#### Scenario: Key-shaped status
- **WHEN** the API answers with a status containing a `pplx-` key-shaped token
- **THEN** the error message and any stored row show the token removed and the status cut to 64 characters

#### Scenario: Answer left alone
- **WHEN** a model's answer text contains a `pplx-` shaped example
- **THEN** the answer is returned as received

### Requirement: Usage in the result
The result SHALL summarize the call's usage: input, output and total tokens when reported, `cost_usd` as an exact decimal string and `cost_source` `reported`, `computed` or `none`, all derived by the same parser the usage record uses. `perplexity_chat` sends and `perplexity_jobs` results carry this same summary.

#### Scenario: Reported cost
- **WHEN** the API returns the recorded structured-output response with total cost 0.00147
- **THEN** the usage summary has `cost_usd` `"0.00147"`, `cost_source` `reported` and 3678 total tokens

### Requirement: Ask is recorded
Each ask that reaches the API SHALL be recorded once as a usage event: tool `perplexity_ask`, API family `agent`, the requested preset when a depth was used, the resolved model, the response id, the project name and the measured latency. A completed response is `ok`; an incomplete one is `unexpected_response` keeping its reported cost; a failed call carries its error category and no usage.

#### Scenario: Successful ask
- **WHEN** an ask completes with the recorded fast response
- **THEN** exactly one event exists with status `ok`, preset `fast`, model `openai/gpt-6-luna`, the response id and cost source `reported`

#### Scenario: Incomplete ask
- **WHEN** an ask returns the recorded truncated response
- **THEN** one event exists with status `unexpected_response` and cost 10000 nano-USD with source `reported`

#### Scenario: Failed ask
- **WHEN** the API answers a valid ask with a recorded 400 error body
- **THEN** one event exists with status `invalid_request`, cost 0 and source `none`, and the tool returns that error

#### Scenario: Nothing recorded before a call
- **WHEN** an ask fails local validation
- **THEN** no usage event exists

### Requirement: Ask follows the recording order
The ask SHALL validate its arguments and the project name first, resolve the project in a unit of work that has committed before the call, make the upstream call holding no write unit, and record the event while no write unit is open. A project created for a failed call survives it.

#### Scenario: Project resolved first
- **WHEN** an ask names project `research`, which does not exist, and the API fails
- **THEN** the project exists afterwards and one failure event carries the name `research`

#### Scenario: Write lock free during the call
- **WHEN** an ask's upstream call is slower than the busy timeout and another call writes meanwhile
- **THEN** the other write succeeds

#### Scenario: Recording cannot change the result
- **WHEN** the database is locked past the busy timeout when the event is recorded
- **THEN** the ask still returns its normal result

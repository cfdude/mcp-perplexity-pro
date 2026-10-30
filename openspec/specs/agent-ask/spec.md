# agent-ask Specification

## Purpose
Defines `perplexity_ask`, the synchronous single-turn grounded question tool built on the Agent API: how the caller picks depth or a model, narrows the search, asks for structured output, what the result contains, and that every call is recorded as spend.

## Requirements

### Requirement: Ask tool
The server SHALL provide `perplexity_ask`, a stateless synchronous tool that answers one `query` with web-grounded search. Its description SHALL state approximate costs per depth (fast about $0.001 to $0.002, low about $0.004 to $0.02, medium about $0.016 to $0.05), the active routing mode and what a call with no selector uses (the default model, or in `dynamic` mode the tier the server picks from the prompt), say that the default model's cost differs from the per-depth figures (the README and `perplexity_usage` give it), and say that it never waits for a background run. It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` false and `openWorldHint` true.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_ask` is present with typed parameters, an output schema, and a description naming the three costs, the mode and what a nameless call uses

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
`depth` SHALL be `fast`, `low` or `medium` and selects the API preset of that name. A call that names no depth, tier or model SHALL NOT default to a preset in `standard` and `custom` mode: the routing mode supplies the model (see `routing-config`); in `dynamic` mode the dynamic classifier may pick a tier that runs a preset. `high` and `xhigh` SHALL be refused with `invalid_request` pointing to `perplexity_research`, because a run at those depths can last minutes and cost dollars.

#### Scenario: Default depth
- **WHEN** a client asks with no depth, no tier and no model
- **THEN** in `standard` mode the request names the mode's default model (with defaults, `perplexity/sonar`) and no preset

#### Scenario: Medium depth
- **WHEN** a client asks with depth `medium`
- **THEN** the request has `effort` `medium`

#### Scenario: High depth refused
- **WHEN** a client asks with depth `high`
- **THEN** the call fails with `invalid_request` naming `perplexity_research` and no request reaches the API

### Requirement: Explicit model
An explicit `model` SHALL replace the preset: the request names the model and no preset, grounds it with the web search tool and a step budget of 3, unless `search` is false, which sends no tools. The conflicts between `depth`, `tier` and `model` are owned by `routing-config` ("Resolution order"). `search` false SHALL be accepted on any model route (the mode's default model, a tier or an explicit `model`) and SHALL fail with `invalid_request` with `depth`, because a preset always searches. `search` true is always accepted.

#### Scenario: Model with search
- **WHEN** a client asks with model `openai/gpt-6-luna`
- **THEN** the request names that model and no preset, carries one web search tool and a step budget of 3

#### Scenario: Model without search
- **WHEN** a client asks with that model and `search` false
- **THEN** the request carries no tools and the result's sources are empty

#### Scenario: Conflicting options
- **WHEN** a client passes `search` false together with a depth (a depth with a model is owned by `routing-config`, "Selectors are mutually exclusive")
- **THEN** the call fails with `invalid_request` and no request reaches the API

#### Scenario: Search off on the default route
- **WHEN** a client passes `search` false and no depth, tier or model in `standard` mode
- **THEN** the request names the default model and carries no tools

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
`recency` SHALL be one of `hour`, `day`, `week`, `month`, `year`; `after` and `before` strict `YYYY-MM-DD` dates with `after` not later than `before`; `country` two ASCII letters; `max_results` 1 to 50. Any search option (`domains`, `recency`, `after`, `before`, `country` or `max_results`) with `search` false SHALL fail. Each failure is `invalid_request` naming the option, before any upstream call.

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
- **WHEN** a client passes `recency` `week`, or `domains` `["python.org"]`, with a model and `search` false
- **THEN** each call fails with `invalid_request` naming the option

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
- **THEN** the request has `effort` `low` and no `tools` member

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
When `json_schema` is given (root `type` `object`), the request SHALL carry a `json_schema` response format named `answer` and no `strict` member. The result SHALL keep the API's raw JSON text as the answer and add the parsed value as `answer_json` when it parses, else null with a warning. In `answer_json`, every string value SHALL have a trailing run of citation markers removed, where a marker is exactly `[N]` (ASCII digits, 1 to 999, no leading zero) or `[web:N]` (ASCII digits, 0 to 999), each with the ASCII whitespace before it; the cleaning SHALL run in time linear in the string's length, SHALL NOT raise, and SHALL NOT leave a half-cleaned value: if it fails the uncleaned value is returned with a warning that cleaning was skipped. A parsed value nested deeper than 100 levels SHALL be returned as null with a warning, because the result could not be serialised. One warning per call SHALL read `Removed N citation marker(s) from string values of answer_json; the answer text is unchanged.` with the total N. The raw answer text, the keys, non-string values, other bracket forms (`[1,2]`, `[1-3]`, `[^1]`, `[fetch:3]`, `[2024]`) and any marker not at the end of a string SHALL be left as the API gave them; a bare marker glued to text (`x[1]`) is removed like any other. A non-object root SHALL fail with `invalid_request` before any call; a schema the API rejects SHALL surface as `invalid_request` with the API's message and a hint naming `json_schema`.

#### Scenario: Structured answer
- **WHEN** a client passes a schema for `{city, population}` and the API returns the recorded structured response
- **THEN** the answer text is `{"city":"Paris","population":2050000}` and `answer_json` equals that object

#### Scenario: Trailing markers removed
- **WHEN** the API's JSON text is `{"name":"Acme Corp [1][3]","note":"see [2] for details"}`
- **THEN** `answer_json` is `{"name":"Acme Corp","note":"see [2] for details"}`, the answer text is unchanged and the warning reads `Removed 2 citation marker(s) from string values of answer_json; the answer text is unchanged.`

#### Scenario: Nested values
- **WHEN** the parsed value is `{"rows":[{"co":"Acme [web:12]"},{"co":"Bolt"}]}`
- **THEN** `answer_json` is `{"rows":[{"co":"Acme"},{"co":"Bolt"}]}` and the warning says 1 marker was removed

#### Scenario: Only markers
- **WHEN** a string value is `[1][2]`
- **THEN** it becomes the empty string

#### Scenario: Other leaves and forms are kept
- **WHEN** the values are the number `2050000`, the string `see [2024]`, `a[1,2]` and `[0]`
- **THEN** they are returned as given (`[0]` has a leading zero, so it is not a marker)

#### Scenario: Long input stays fast
- **WHEN** a string value is 500000 spaces followed by `x`, and another is 500000 characters of `[1]` repeated
- **THEN** cleaning each takes well under one second and the second becomes the empty string

#### Scenario: Deeply nested value
- **WHEN** the parsed value nests deeper than 100 levels
- **THEN** the result still carries the answer, the sources and the usage, `answer_json` is null and a warning says it is nested deeper than 100 levels (the structured result could not be serialised beyond about 300 levels)

#### Scenario: A value at the limit
- **WHEN** the parsed value nests exactly 100 levels
- **THEN** it is cleaned as usual
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
`sources` SHALL list the pages the run found or fetched, from its search results and fetched pages, de-duplicated by URL in first-seen order, each with `url`, `title`, `date` when known, `ids` (every distinct result `id` the API gave that URL, in first-seen order, at most 64 of them with a warning naming how many were dropped, empty when it gave none) and `id` (the first of `ids`, or null; a source stored before this change has `id` and no `ids`). Research results (`perplexity_jobs` result) and chat results share this shape and these rules. The tool SHALL NOT rewrite or annotate the answer text with source numbers: the API's `annotations` are always empty. In the recorded responses (three markers in one fixture, `[web:1]`, `[web:11]` and `[web:21]`, plus bare `[1]` and `[3]` in the fast fixtures) an inline marker `[N]` or `[web:N]` names the search result whose `id` is `N`; a fetched page has no `id`, so a marker cannot be matched to one and the tool SHALL NOT claim to. The text rendering of the sources (the readable `content` of ask and of `perplexity_jobs` result) SHALL show a source's `ids` beside its title and URL, so a text-only client can find the source a marker names; a source with no ids is rendered as before.

#### Scenario: Search sources
- **WHEN** the API returns the recorded fast response with filters
- **THEN** `sources` holds its search results in order, each URL once

#### Scenario: Fetched page as a source
- **WHEN** the API returns the recorded low-depth response that fetched a URL and ran no search
- **THEN** `sources` holds the fetched page with no result id and empty `ids`

#### Scenario: Repeated URL
- **WHEN** two search result items contain the same URL
- **THEN** it appears once, at its first position

#### Scenario: A URL seen under several ids
- **WHEN** the recorded cancelled research response lists `https://crates.io/crates/rs-stats` under ids 10 and 71
- **THEN** that source has `ids` `[10, 71]` and `id` 10

#### Scenario: A fetched page first, then a search row for the same URL
- **WHEN** a fetched page and a later search result share a URL
- **THEN** one source exists, in the position of the first, whose title and date are the first row's and whose `ids` holds the search row's id

#### Scenario: Ids are rendered
- **WHEN** a source has `ids` `[10, 71]`
- **THEN** its line in the readable result shows `ids 10, 71` beside its title and URL, and a source with no ids shows no ids text

#### Scenario: Ids are bounded
- **WHEN** one URL comes back under 200000 distinct ids
- **THEN** its `ids` holds the first 64, a warning says the rest were dropped and the digest completes in well under two seconds

#### Scenario: Every cited marker has a source
- **WHEN** the recorded completed research response cites `[web:1]`, `[web:11]` and `[web:21]`
- **THEN** each of ids 1, 11 and 21 appears in some source's `ids`

#### Scenario: Stored job from before this change
- **WHEN** `perplexity_jobs` result reads a stored job whose sources hold only `id`
- **THEN** it returns them with `ids` empty and nothing fails

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
Every string from the API that is returned or stored (a status shown verbatim, an incomplete reason, an error text, a warning built from one) SHALL have the configured key and key-shaped tokens removed, then be cut to 64 characters for a status, 200 for a reason and 2000 for an error text. Caller and model content (query, instructions, messages, titles, answers, source titles and URLs) is stored and returned as given, except that the configured key itself is replaced by `[redacted]`.

#### Scenario: Key-shaped status
- **WHEN** the API answers with a status containing a `pplx-` key-shaped token
- **THEN** the error message and any stored row show the token removed and the status cut to 64 characters

#### Scenario: Answer left alone
- **WHEN** a model's answer text contains a `pplx-` shaped example
- **THEN** the answer is returned as received

#### Scenario: Configured key in answer
- **WHEN** a model's answer contains the configured key, beside a `pplx-` shaped example that is not the key
- **THEN** the returned answer holds `[redacted]` in place of the key and the example as given

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

### Requirement: Agent requests name the preset as effort
Every Agent API request the server builds (an ask, a chat send, a research submit) SHALL name its preset in the body field `effort` and SHALL NOT send `preset`, which the API keeps only as a deprecated alias. The preset names and the tools' `depth` arguments are unchanged.

#### Scenario: An ask at a depth
- **WHEN** a client asks with `depth` `medium`
- **THEN** the request body has `effort` `medium` and no `preset` key

#### Scenario: A research submit
- **WHEN** a client submits research at its default depth
- **THEN** the background request has `effort` equal to that depth and no `preset` key

#### Scenario: A chat send at a depth
- **WHEN** a chat send names `depth` `fast`
- **THEN** its request has `effort` `fast` and no `preset` key

### Requirement: The effort field means the preset name
Wherever the Agent and routing specs (`agent-ask`, `agent-chat`, `agent-research`, `routing-config`) say a request names or has a preset, this body field is meant. It SHALL carry the preset name only and is unrelated to `reasoning.effort` and to the model matrix's `efforts`.

#### Scenario: Reading a routing scenario
- **WHEN** `routing-config` says a request names preset `medium` and no model
- **THEN** the request has `effort` `medium` and no `model` key

### Requirement: Versioned effort values in responses are read as before
A response whose `effort` and `preset` fields carry a versioned value (such as `fast@2026-10-16.0`) SHALL be digested, stored and recorded exactly as one that names the plain preset: the preset recorded on usage events and chat turns is the name the request asked for, not the response's value.

#### Scenario: A versioned response
- **WHEN** an ask at `depth` `fast` receives a response whose `effort` and `preset` are `fast@2026-10-16.0`
- **THEN** the result is digested as before, the usage event records preset `fast`, and a later chat follow-up still recovers its tier from the stored preset

## Purpose

Defines `perplexity_search`, the tool that returns ranked web search results as structured data for the caller to read (no model answer): its arguments and local validation, the request it builds, the result shape, how third-party text is handled, what a request costs, and that every request is recorded as spend.

## ADDED Requirements

### Requirement: Search tool
The server SHALL provide `perplexity_search`, a synchronous stateless tool that runs one web search and returns the ranked results. It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` false and `openWorldHint` true. Its description SHALL state the cost per request (fast $0.001, web $0.005), that titles and snippets are third-party web content, that several queries are merged into one list, and that `people` search is not offered.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_search` is present with typed parameters, an output schema, the two costs, the third-party-content wording and the merge wording in its description

#### Scenario: Result validates
- **WHEN** a search succeeds
- **THEN** its structured content validates against the advertised output schema and its text content lists the results

### Requirement: Query
`query` SHALL be one string or a list of one to five strings. Every query SHALL be non-blank and at most 8192 characters (the API's own limit). An empty list, a sixth query, a blank query or a longer one SHALL fail with `invalid_request` naming `query` before any upstream call, project creation or usage event; the API bills a whitespace-only query as an empty 200.

#### Scenario: Blank query
- **WHEN** a client searches for `"   "`
- **THEN** the call fails with `invalid_request` naming `query`, nothing is sent and no event or project is created

#### Scenario: Too many queries
- **WHEN** a client passes six queries, or an empty list
- **THEN** each call fails with `invalid_request` naming `query` and nothing is sent

#### Scenario: One string and a list
- **WHEN** a client passes `"python asyncio"`, and separately a list of three queries
- **THEN** the first request carries the string and the second carries the three-element list

### Requirement: Search type
`search_type` SHALL be `fast` (the default) or `web`, and the request SHALL always name it, so the API's own default (`web`, five times the price) is never used by omission. Any other value SHALL fail with `invalid_request` before any call; `people` is refused with a message saying it is not offered.

#### Scenario: Default is fast
- **WHEN** a client searches with no `search_type`
- **THEN** the request carries `search_type` `fast`

#### Scenario: Web search
- **WHEN** a client passes `search_type` `web`
- **THEN** the request carries `web`

#### Scenario: People refused
- **WHEN** a client passes `search_type` `people`
- **THEN** the call fails with `invalid_request` and nothing is sent

### Requirement: Result count
`max_results` SHALL be a whole number from 1 to 20 for both search types (the schema says 50; the API refuses 21 and 0). It is a total across all queries of the request, not per query. When omitted it is not sent and the API's default of 10 applies. Another value SHALL fail with `invalid_request` naming `max_results` before any call.

#### Scenario: Out of range
- **WHEN** a client passes `max_results` 21, or 0
- **THEN** each call fails with `invalid_request` naming `max_results` and nothing is sent

#### Scenario: Total across queries
- **WHEN** three queries and `max_results` 10 are sent and the API returns the recorded merged response
- **THEN** the result holds ten results in the API's order and `query_count` is 3

### Requirement: Domain filters are validated locally
`domains` SHALL hold at most 20 entries of at most 253 characters, none empty, `-` alone or containing whitespace, either all allowed or all denied with a `-` prefix. A list that mixes both SHALL fail with `invalid_request` naming `domains` before any call, because the API accepts it and silently ignores the denied entries. The list is sent as `search_domain_filter`.

#### Scenario: Mixed list
- **WHEN** a client passes domains `["python.org", "-reddit.com"]`
- **THEN** the call fails with `invalid_request` naming `domains` and nothing is sent

#### Scenario: Allowlist and denylist
- **WHEN** a client passes `["python.org"]`, and separately `["-reddit.com"]`
- **THEN** each request carries that list as `search_domain_filter`

#### Scenario: Bad entries
- **WHEN** a client passes 21 domains, an empty string, `-`, or an entry of 254 characters
- **THEN** each call fails with `invalid_request` naming `domains`

### Requirement: Date filters are validated locally
`after`, `before`, `updated_after` and `updated_before` SHALL be strict `YYYY-MM-DD` calendar dates, sent as `MM/DD/YYYY` built from the date's own month, day and four-digit year (no locale formatter) in `search_after_date_filter`, `search_before_date_filter`, `last_updated_after_filter` and `last_updated_before_filter`. `after` SHALL NOT be later than `before`, nor `updated_after` than `updated_before`. Each failure is `invalid_request` naming the option, before any call.

#### Scenario: Date conversion
- **WHEN** a client passes `after` `2026-09-01` and `before` `2026-10-01`
- **THEN** the request carries `search_after_date_filter` `09/01/2026` and `search_before_date_filter` `10/01/2026`

#### Scenario: Early year formatted
- **WHEN** a client passes `after` `0999-01-02`
- **THEN** the request carries `search_after_date_filter` `01/02/0999`

#### Scenario: Malformed or impossible date
- **WHEN** a client passes `after` `09/01/2026`, `2026-13-40` or `yesterday`
- **THEN** the call fails with `invalid_request` naming `after` and nothing is sent

#### Scenario: Dates out of order
- **WHEN** `after` is `2026-10-01` and `before` is `2026-09-01`
- **THEN** the call fails with `invalid_request`

### Requirement: Recency filter is validated locally
`recency` SHALL be one of `hour`, `day`, `week`, `month`, `year`, sent as `search_recency_filter`, and SHALL NOT be combined with any of the four date options: the API refuses it with a publication date and accepts it with a last-updated date although documented as exclusive, so the effect of that combination is unknown. Each failure is `invalid_request` naming `recency`, before any call.

#### Scenario: Recency sent
- **WHEN** a client passes `recency` `month`
- **THEN** the request carries `search_recency_filter` `month`

#### Scenario: Recency with a date
- **WHEN** a client passes `recency` `week` with `after`, or with `updated_after`
- **THEN** each call fails with `invalid_request` naming `recency` and nothing is sent

#### Scenario: Bad recency
- **WHEN** a client passes `recency` `decade`
- **THEN** the call fails with `invalid_request` naming `recency`

### Requirement: Language and country are validated locally
`languages` SHALL hold at most 20 entries (the API refuses 21; its prose says 10 and accepts 11), each two lowercase ASCII letters, sent as `search_language_filter`; whether a code is a real ISO 639-1 code is left to the API. `country` SHALL be two ASCII letters in either case and is sent in upper case; whether it is a real country is left to the API. Each local failure is `invalid_request` naming the option, before any call.

#### Scenario: Upper-case language refused
- **WHEN** a client passes languages `["EN"]`, `["eng"]` or 21 codes
- **THEN** each call fails with `invalid_request` naming `languages` and nothing is sent

#### Scenario: Accepted
- **WHEN** a client passes languages `["en", "fr"]` and country `us`
- **THEN** the request carries `search_language_filter` `["en", "fr"]` and `country` `US`

#### Scenario: Unknown code reaches the API
- **WHEN** a client passes languages `["xx"]` and the API returns the recorded 400
- **THEN** the call fails with `invalid_request` carrying the API's message

### Requirement: Content budget
`max_tokens` (1 to 16384) caps the page content returned across all results and `max_tokens_per_page` (1 to 4096) per result; both are this server's own bounds, not provider limits, and are sent unchanged when given and omitted otherwise. A value outside its bounds SHALL fail with `invalid_request` naming the option before any call.

#### Scenario: Passed through
- **WHEN** a client passes `max_tokens` 128 and `max_tokens_per_page` 64
- **THEN** the request carries both values

#### Scenario: Out of bounds
- **WHEN** a client passes `max_tokens` 0 or 16385, or `max_tokens_per_page` 4097
- **THEN** each call fails with `invalid_request` naming the option and nothing is sent

### Requirement: Budget warning
When `max_tokens` is given and fewer results come back than `max_results` (when `max_results` is omitted: than the API's default of 10), the result SHALL carry a warning that the budget may have dropped results, because the API drops whole results to fit it. When `max_results` was omitted the warning SHALL also say the query may simply have had fewer hits, as the two causes cannot be told apart. Without `max_tokens` there is no such warning.

#### Scenario: Budget drops results
- **WHEN** a client asks for three results with `max_tokens` 1 and the API returns the recorded one-result response
- **THEN** the result has count 1 and a warning naming `max_tokens`

#### Scenario: Default count
- **WHEN** a client passes `max_tokens` 1 with no `max_results` and the API returns four results
- **THEN** the result carries a warning naming `max_tokens` that also says the query may have had few hits

#### Scenario: No shortfall or no budget
- **WHEN** a client asks for three results with `max_tokens` 128 and three come back, or passes no `max_tokens` and fewer come back than asked
- **THEN** the result carries no budget warning

### Requirement: Request carries only what was asked
The request SHALL hold `query`, `search_type` and exactly the options the caller gave, under the API's top-level field names, and nothing else: no option is invented and no unknown field is sent (the API silently accepts unknown fields, so a misspelled one would be billed and do nothing). An empty `domains` or `languages` list counts as not given and is not sent.

#### Scenario: Minimal request
- **WHEN** a client searches for `"python"` with no options
- **THEN** the request body is `{"query": "python", "search_type": "fast"}`

#### Scenario: Empty lists
- **WHEN** a client passes `domains` `[]` and `languages` `[]`
- **THEN** the request carries neither field

#### Scenario: Recorded request shapes
- **WHEN** the options of each recorded request that the tool accepts as given are passed to the tool
- **THEN** the request equals that recorded request

#### Scenario: Recorded requests that are not reproduced
- **WHEN** the options of the six recorded requests the API accepted but this tool does not send as recorded are given (mixed domains, an upper-case language, recency with a last-updated date, a whitespace-only query, an omitted `search_type`, an unknown field)
- **THEN** the first four fail with `invalid_request`, the omitted `search_type` is sent as `fast`, and the unknown field is not sendable at all

### Requirement: Results
The result SHALL hold `results`, in the order the API ranks them, each with `title`, `url`, `snippet`, `date` and `last_updated` (the dates as the API gives them, `YYYY-MM-DD`, or null when it gives none); `count` (the results kept); `query_count`; `search_type`; `request_id`; `cost_usd`; `cost_source`; `latency_ms`; `project`; and `warnings`. A response with no results SHALL be a normal result with count 0 and a warning, not an error: the request was made and is billed.

#### Scenario: Fast single query
- **WHEN** the API returns the recorded fast single-query response
- **THEN** the result holds its five results in order with their titles, urls, snippets and dates, count 5, `search_type` `fast` and its id as `request_id`

#### Scenario: Missing dates
- **WHEN** a result has no `date` key
- **THEN** its `date` is null and its `last_updated` is kept

#### Scenario: No results
- **WHEN** the API returns the recorded response for a date range with no hits
- **THEN** the result has count 0 and a warning, and one event is recorded

### Requirement: Unusable results are dropped
A result that is not an object, or whose `url` is missing, null, not text or empty, SHALL be dropped (a pointer to nowhere is not a result) and one warning SHALL count the drops; `count` is the number kept. A `title` or `snippet` that is not text SHALL become an empty string and a `date` or `last_updated` that is not text SHALL become null, without losing the result.

#### Scenario: Result without a url
- **WHEN** a response holds five results and one has no `url`
- **THEN** the result holds the other four in order, count 4 and a warning that one result was dropped

#### Scenario: Non-object item
- **WHEN** a response holds a string among its results
- **THEN** the string is dropped with the same warning and the rest are returned

#### Scenario: Null and non-text fields
- **WHEN** a result has a null `title`, a numeric `snippet` and a numeric `date`
- **THEN** it is returned with an empty title and snippet, a null date and its url, and nothing is dropped

### Requirement: Several queries are merged
For a list of queries the result SHALL be the API's one flat list in the API's order, with `query_count` set and a warning that the API merges the queries and does not say which query produced which result. The tool SHALL NOT invent an attribution, add or reorder a result, and removes only a result dropped under "Unusable results are dropped".

#### Scenario: Three queries
- **WHEN** three queries are searched and the API returns the recorded merged response
- **THEN** the results equal that response's results in order and a warning says the results cannot be attributed to a query

#### Scenario: Repeated query
- **WHEN** the same query is sent twice
- **THEN** the request carries both and the result is the API's list, with the warning

### Requirement: Third-party text is scrubbed
Titles, snippets, urls, `date` and `last_updated` are third-party content and SHALL be returned as received except that the configured API key is replaced by `[redacted]`; a `pplx-` shaped example or a documented model id inside them is kept. Every other string taken from the API (the request id) SHALL have the key and key-shaped tokens removed, then be cut to 128 characters.

#### Scenario: Key in a snippet
- **WHEN** a snippet contains the configured key beside the text `pplx-embed-v1-0.6b` and a `pplx-` shaped example that is not the key
- **THEN** the returned snippet holds `[redacted]` in place of the key and the other two as received

#### Scenario: Key in a date field
- **WHEN** `last_updated` or `date` contains the configured key
- **THEN** the returned field holds `[redacted]` in its place

#### Scenario: Key-shaped request id
- **WHEN** the response `id` contains a key-shaped token
- **THEN** the returned `request_id` and the stored event show it removed

### Requirement: Third-party text is capped
After the key is replaced, each title SHALL be cut to 500 characters, each url to 2048, each snippet to 20000, and each `date` and `last_updated` to 64 (the cap the Agent tool applies to a source date), and the result SHALL carry one warning counting the fields that were cut. The caps are this server's own bound on a result's size, not provider limits.

#### Scenario: Oversized snippet
- **WHEN** a snippet is 30000 characters long
- **THEN** the returned snippet is 20000 characters and a warning says one field was cut

#### Scenario: Oversized last_updated
- **WHEN** `last_updated` is 100 characters long
- **THEN** the returned value is 64 characters and a warning says one field was cut

#### Scenario: Nothing cut
- **WHEN** every field of the recorded fast response is within its cap
- **THEN** the result carries no cut warning

### Requirement: Cost of a search
The cost of a request SHALL be one billing unit at the documented price of its search type (fast $0.001, web $0.005), however many queries it holds. No parser is registered for `search`, so a `usage` field, if one ever appears, is kept in the event's usage record as received but not read as a cost report; the computed cost stands until a parser is added after a probe. The result carries `cost_usd` as an exact decimal string and `cost_source` `computed`.

#### Scenario: Fast single
- **WHEN** a fast single-query search succeeds
- **THEN** the result has `cost_usd` `"0.001"` and `cost_source` `computed`

#### Scenario: Web and multi-query
- **WHEN** a web search succeeds, and separately a fast three-query search
- **THEN** the costs are `"0.005"` and `"0.001"`

#### Scenario: A usage field is kept but not a cost report
- **WHEN** a response carries an extra `usage` object with a cost
- **THEN** the result and the event have the computed cost and source `computed`, and the event's usage record holds that object as received

### Requirement: Search is recorded
Each search that reaches the API SHALL be recorded once as a usage event: tool `perplexity_search`, API family `search`, no model and no preset, the response id as request id, the project name, the measured latency, and the computed cost with source `computed`. A response with results or without is `ok`; a failed request carries its error category with cost 0 and source `none`; a 200 that cannot be read is `unexpected_response`.

#### Scenario: Successful search
- **WHEN** a fast search completes with the recorded response
- **THEN** exactly one event exists with status `ok`, API family `search`, tool `perplexity_search`, the response id, cost 1000000 nano-USD and source `computed`

#### Scenario: Empty result is recorded
- **WHEN** a search returns the recorded response with no results
- **THEN** one event exists with status `ok` and the same computed cost

#### Scenario: Failed search
- **WHEN** the API answers a valid search with a recorded 400 body, or with 429, or with 503
- **THEN** one event exists with status `invalid_request`, `rate_limited` or `upstream_failure`, cost 0 and source `none`, and the tool returns that error

#### Scenario: Unreadable 200
- **WHEN** the API answers 200 with a body that has no `results`
- **THEN** the call fails with `unexpected_response` and one event with that status, cost 0 and source `none` exists

#### Scenario: Nothing recorded before a call
- **WHEN** a search fails local validation
- **THEN** no usage event and no project exist for it

### Requirement: Project
`project` SHALL be an optional project name, `default` when omitted, checked against the server's project-name rules before any upstream call. An invalid name SHALL fail with `invalid_request` before any call, project creation or usage event. A valid name that does not exist is created before the call, and the result and the event carry the name.

#### Scenario: Default project
- **WHEN** a client searches with no `project`
- **THEN** the result and the usage event carry the project `default`

#### Scenario: Invalid project name
- **WHEN** a client passes the project `../x`
- **THEN** the call fails with `invalid_request`, nothing is sent and no project or event is created

### Requirement: Search follows the recording order
The search SHALL validate its arguments and the project name first, resolve the project in a unit of work that has committed before the call, make the upstream call holding no write unit, and record the event while no write unit is open. It writes nothing of its own afterwards. A project created for a failed call survives it.

#### Scenario: Project resolved first
- **WHEN** a search names project `lookup`, which does not exist, and the API fails
- **THEN** the project exists afterwards and one failure event carries the name `lookup`

#### Scenario: Write lock free during the call
- **WHEN** a search's upstream call is slower than the busy timeout and another call writes meanwhile
- **THEN** the other write succeeds

#### Scenario: Recording cannot change the result
- **WHEN** the database is locked past the busy timeout when the event is recorded
- **THEN** the search still returns its normal result

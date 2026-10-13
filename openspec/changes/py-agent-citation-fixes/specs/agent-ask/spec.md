## MODIFIED Requirements

### Requirement: Sources
`sources` SHALL list the pages the run found or fetched, from its search results and fetched pages, de-duplicated by URL in first-seen order, each with `url`, `title`, `date` when known, `ids` (every distinct result `id` the API gave that URL, in first-seen order, empty when it gave none) and `id` (the first of `ids`, or null). The tool SHALL NOT rewrite or annotate the answer text with source numbers: the API's `annotations` are always empty. In the recorded responses (three markers in one fixture, `[web:1]`, `[web:11]` and `[web:21]`, plus bare `[1]` and `[3]` in the fast fixtures) an inline marker `[N]` or `[web:N]` names the search result whose `id` is `N`; a fetched page has no `id`, so a marker cannot be matched to one and the tool SHALL NOT claim to. The text rendering of the sources (the readable `content` of ask and of `perplexity_jobs` result) SHALL show a source's `ids` beside its title and URL, so a text-only client can find the source a marker names; a source with no ids is rendered as before.

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

#### Scenario: Every cited marker has a source
- **WHEN** the recorded completed research response cites `[web:1]`, `[web:11]` and `[web:21]`
- **THEN** each of ids 1, 11 and 21 appears in some source's `ids`

#### Scenario: Stored job from before this change
- **WHEN** `perplexity_jobs` result reads a stored job whose sources hold only `id`
- **THEN** it returns them with `ids` empty and nothing fails

### Requirement: Structured output
When `json_schema` is given (root `type` `object`), the request SHALL carry a `json_schema` response format named `answer` and no `strict` member. The result SHALL keep the API's raw JSON text as the answer and add the parsed value as `answer_json` when it parses, else null with a warning. In `answer_json`, every string value SHALL have a trailing run of citation markers removed, where a marker is exactly `[N]` (ASCII digits, 1 to 999, no leading zero) or `[web:N]` (ASCII digits, 0 to 999), each with the ASCII whitespace before it; the cleaning SHALL run in time linear in the string's length and SHALL NOT raise: if it cannot complete (for example a value nested beyond what it can walk) the uncleaned value is returned with a warning that cleaning was skipped. One warning per call SHALL read `Removed N citation marker(s) from string values of answer_json; the answer text is unchanged.` with the total N. The raw answer text, the keys, non-string values, other bracket forms (`[1,2]`, `[1-3]`, `[^1]`, `[fetch:3]`, `[2024]`) and any marker not at the end of a string SHALL be left as the API gave them; a bare marker glued to text (`x[1]`) is removed like any other. A non-object root SHALL fail with `invalid_request` before any call; a schema the API rejects SHALL surface as `invalid_request` with the API's message and a hint naming `json_schema`.

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
- **WHEN** the parsed value is nested to the deepest level `json.loads` accepts
- **THEN** the result still carries the answer, the sources and the usage, `answer_json` is the uncleaned value and a warning says cleaning was skipped

#### Scenario: Root not an object
- **WHEN** a client passes a schema with root type `array`
- **THEN** the call fails with `invalid_request` and no request reaches the API

#### Scenario: API rejects the inner schema
- **WHEN** the API returns the recorded generic 400 for a schema with an invalid inner type
- **THEN** the call fails with `invalid_request` and the message names `json_schema`

#### Scenario: Answer is not JSON
- **WHEN** the model's answer text does not parse as JSON
- **THEN** `answer_json` is null and a warning says so, and the answer text is still returned

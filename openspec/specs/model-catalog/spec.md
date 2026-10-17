# model-catalog Specification

## Purpose
Lets a client discover which models the Perplexity Agent API offers and what they cost, from live data, so model and price choices are never taken from a hardcoded list.

## Requirements

### Requirement: Model listing tool
The server SHALL provide a tool `perplexity_models` that returns the models available to the configured key, each with `id`, `provider` (the API's `owned_by` value) and pricing fields `input`, `output`, `cache_read`, `cache_write` and `unit` when the API supplies them. Results SHALL come from the live Perplexity model list.

#### Scenario: Listing all models
- **WHEN** a client calls `perplexity_models` with no arguments
- **THEN** the result contains one entry per model returned by the API, each with `id`, `provider` and its pricing fields exactly as the API reported them

#### Scenario: Model without pricing
- **WHEN** the API returns a model with no `pricing` object
- **THEN** that model is still listed and its pricing fields are null

#### Scenario: Partial pricing
- **WHEN** the API returns a model whose `pricing` lacks `cache_write`
- **THEN** the other pricing fields are returned as reported and `cache_write` is null

#### Scenario: Field names match the recorded response
- **WHEN** the tool is run against the recorded `/v1/models` fixture
- **THEN** every returned `id`, `provider` and pricing value equals the fixture's `id`, `owned_by` and `pricing` values

### Requirement: Provider filter
The tool SHALL accept an optional `provider` argument and, when given, return only models whose provider equals it, compared case-insensitively.

#### Scenario: Filtering by provider
- **WHEN** a client calls `perplexity_models` with `provider` set to `anthropic`
- **THEN** every returned entry has provider `anthropic` and no other provider appears

#### Scenario: Unknown provider
- **WHEN** a client passes a provider that matches no model
- **THEN** the result has an empty model list and names the providers that do exist

### Requirement: Documented presets are labeled as documented
The result SHALL list the Agent API preset names `fast`, `low`, `medium`, `high` and `xhigh` in a separate section labeled as taken from documentation, with the date they were recorded. Presets SHALL NOT be presented as live data.

#### Scenario: Presets with a provider filter
- **WHEN** a client calls `perplexity_models` with a `provider` filter
- **THEN** the preset section is still included

#### Scenario: Preset section
- **WHEN** a client calls `perplexity_models`
- **THEN** the result includes the five preset names under a section whose `source` is `documentation` and whose `as_of` is a date

### Requirement: Caching with explicit refresh
The server SHALL cache the live model list for a configurable time (default one hour) and serve repeat calls from the cache. A `refresh` argument set to true SHALL bypass the cache.

#### Scenario: Cache hit
- **WHEN** a client calls the tool twice within the cache time
- **THEN** only one request is made to the Perplexity API

#### Scenario: Cold cache under concurrency
- **WHEN** five calls arrive at the same time with an empty cache
- **THEN** exactly one request is made to the Perplexity API and all five receive the same list

#### Scenario: Forced refresh
- **WHEN** a client calls the tool with `refresh` true
- **THEN** a new upstream request is made and the cache is replaced

### Requirement: Stale data on upstream failure
If the live request fails with `rate_limited`, `upstream_failure` or `network_timeout` and a cached list younger than the configured maximum stale age (default 24 hours) exists, the tool SHALL return that list marked `stale` with the cache age. For any other failure, including `authentication` and `forbidden`, or when no usable cached list exists, the tool SHALL fail with the underlying category.

#### Scenario: Upstream down with cache
- **WHEN** a refresh fails with a 5xx and an earlier list is cached
- **THEN** the tool returns the earlier list with `stale` true and its age in seconds

#### Scenario: Upstream down without cache
- **WHEN** the first-ever request fails with a 401
- **THEN** the tool fails with category `authentication` and returns no model list

#### Scenario: Revoked key with a cached list
- **WHEN** a refresh fails with 401 and a cached list exists
- **THEN** the tool fails with category `authentication` and does not return the cached list

#### Scenario: Cache too old
- **WHEN** a refresh fails with a 5xx and the cached list is older than the maximum stale age
- **THEN** the tool fails with category `upstream_failure`

### Requirement: Structured output
The tool SHALL declare an output schema and return structured content that validates against it, in addition to a readable text rendering.

#### Scenario: Output validates
- **WHEN** the tool returns successfully
- **THEN** its structured content validates against the schema advertised in `tools/list`

### Requirement: Active routing is reported
`perplexity_models` SHALL include a `routing` section stating the active mode, the standard model or the three tiers with what each runs (a model id or, for a dynamic tier, a preset name), and whether the live catalog lists each model id (`known`; null for a preset). In `dynamic` mode it SHALL also name the classifier in use (`rules` unless another is configured). The section describes configuration and SHALL be present whatever the `provider` filter is.

#### Scenario: Standard routing section
- **WHEN** a client calls `perplexity_models` against a default server
- **THEN** the result's routing section has mode `standard` and model `perplexity/sonar` with `known` true when the live catalog lists it

#### Scenario: Custom routing section
- **WHEN** the server runs in `custom` mode and one tier model is not in the catalog
- **THEN** the section lists the three tiers and marks that one `known` false

#### Scenario: Dynamic routing section
- **WHEN** a client calls `perplexity_models` against a `dynamic` server with no tier variables set
- **THEN** the section has mode `dynamic`, classifier `rules`, `light` as preset `fast`, `standard` as model `perplexity/sonar` with `known`, and `complex` as preset `medium`

#### Scenario: Catalog unreadable
- **WHEN** the catalog cannot be fetched and no cache exists
- **THEN** the call fails as it does today (the other three channels still carry the routing); with a stale cache the section is built from it and the existing staleness notice applies

#### Scenario: An unlisted id is still used
- **WHEN** a configured model id is `known` false
- **THEN** calls still send it as configured, because the catalog can lag and a typo is reported by the API on the first call

### Requirement: The routing section names the Decisions classifier
In `dynamic` mode with the Decisions classifier the `perplexity_models` routing section SHALL name classifier `decisions` and the decider model it asks, in place of `rules`.

#### Scenario: Decisions classifier section
- **WHEN** a client calls `perplexity_models` against a `dynamic` server with the Decisions classifier
- **THEN** the routing section names classifier `decisions` and the default decider model

### Requirement: The model list reports each model's efforts
`perplexity_models` SHALL give each listed model its effort facts from the matrix (`accepted` and `refused` as lists of levels, and their source) and SHALL include a `matrix` object: its `origin` (`file` or `baseline`), when it was last fetched, and how many `available` matrix models are `unprobed`. A model not in the matrix SHALL be listed without efforts. The facts are those stored; `refresh` on this tool refreshes the catalog list, not the matrix.

#### Scenario: Efforts shown
- **WHEN** a client calls `perplexity_models` against a server whose matrix holds `openai/gpt-5-nano` with `xhigh` and `max` refused
- **THEN** that model's entry lists its accepted levels and the two refused ones

#### Scenario: A model the matrix lacks
- **WHEN** the live list holds an id the matrix does not yet hold
- **THEN** it is listed with no efforts, and the `unprobed` count (which counts `available` matrix rows, not listed ids) is unchanged

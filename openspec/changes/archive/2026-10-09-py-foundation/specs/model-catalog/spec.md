# Spec Delta

## Purpose

Lets a client discover which models the Perplexity Agent API offers and what they cost, from live data, so model and price choices are never taken from a hardcoded list.

## ADDED Requirements

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

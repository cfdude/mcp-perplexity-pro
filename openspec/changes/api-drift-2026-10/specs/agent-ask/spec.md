# Spec Delta

## ADDED Requirements

### Requirement: Agent requests name the preset as effort
Every Agent API request the server builds (an ask, a chat send, a research submit) SHALL name its preset in the body field `effort` and SHALL NOT send `preset`, which the API keeps only as a deprecated alias. Wherever the Agent and routing specs (`agent-ask`, `agent-chat`, `agent-research`, `routing-config`) say a request names or has a preset, this body field is meant. It carries the preset name only and is unrelated to `reasoning.effort` and to the model matrix's `efforts`. The preset names (`fast`, `low`, `medium`, `high`, `xhigh`) and the tools' `depth` arguments are unchanged.

#### Scenario: An ask at a depth
- **WHEN** a client asks with `depth` `medium`
- **THEN** the request body has `effort` `medium` and no `preset` key

#### Scenario: A research submit
- **WHEN** a client submits research at its default depth
- **THEN** the background request has `effort` equal to that depth and no `preset` key

#### Scenario: A chat send at a depth
- **WHEN** a chat send names `depth` `fast`
- **THEN** its request has `effort` `fast` and no `preset` key

### Requirement: Versioned effort values in responses are read as before
A response whose `effort` and `preset` fields carry a versioned value (such as `fast@2026-10-16.0`) SHALL be digested, stored and recorded exactly as one that names the plain preset: the preset recorded on usage events and chat turns is the name the request asked for, not the response's value.

#### Scenario: A versioned response
- **WHEN** an ask at `depth` `fast` receives a response whose `effort` and `preset` are `fast@2026-10-16.0`
- **THEN** the result is digested as before, the usage event records preset `fast`, and a later chat follow-up still recovers its tier from the stored preset

## MODIFIED Requirements

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

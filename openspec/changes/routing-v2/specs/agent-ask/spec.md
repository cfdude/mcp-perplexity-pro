# Spec Delta

## MODIFIED Requirements

### Requirement: Depth selects a preset
`depth` SHALL be `fast`, `low` or `medium` and selects the API preset of that name. A call that names no depth, tier or model SHALL NOT default to a preset in `standard` and `custom` mode: the routing mode supplies the model (see `routing-config`); in `dynamic` mode the router chooses a model and an effort, and only its last fallback rung names a preset. `high` and `xhigh` SHALL be refused with `invalid_request` pointing to `perplexity_research`, because a run at those depths can last minutes and cost dollars.

#### Scenario: Default depth
- **WHEN** a client asks with no depth, no tier and no model
- **THEN** in `standard` mode the request names the mode's default model (with defaults, `perplexity/sonar`) and no preset

#### Scenario: Medium depth
- **WHEN** a client asks with depth `medium`
- **THEN** the request has `effort` `medium`

#### Scenario: High depth refused
- **WHEN** a client asks with depth `high`
- **THEN** the call fails with `invalid_request` naming `perplexity_research` and no request reaches the API

### Requirement: Agent requests name the preset as effort
Every Agent API request the server builds (an ask, a chat send, a research submit) that runs a preset SHALL name it in the body field `effort` and SHALL NOT send `preset`, which the API keeps only as a deprecated alias. The preset names and the tools' `depth` arguments are unchanged. A request for a routed model carries no `effort` (see "A routed model call may carry a reasoning effort").

#### Scenario: An ask at a depth
- **WHEN** a client asks with `depth` `medium`
- **THEN** the request body has `effort` `medium` and no `preset` key

#### Scenario: A research submit
- **WHEN** a client submits research with no depth outside `dynamic` mode
- **THEN** the background request has `effort` `medium` and no `preset` key

#### Scenario: A chat send at a depth
- **WHEN** a chat send names `depth` `fast`
- **THEN** its request has `effort` `fast` and no `preset` key

### Requirement: Ask tool
The server SHALL provide `perplexity_ask`, a stateless synchronous tool that answers one `query` with web-grounded search. Its description SHALL state approximate costs per depth (fast about $0.001 to $0.002, low about $0.004 to $0.02, medium about $0.016 to $0.05), the active routing mode and what a call with no selector uses (the default model, or in `dynamic` mode the model and effort the server picks from the prompt), say that the default model's cost differs from the per-depth figures (the README and `perplexity_usage` give it), and say that it never waits for a background run. It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` false and `openWorldHint` true.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_ask` is present with typed parameters, an output schema, and a description naming the three costs, the mode and what a nameless call uses

#### Scenario: Result validates
- **WHEN** an ask succeeds
- **THEN** its structured content validates against the advertised output schema and its text content carries the answer

## ADDED Requirements

### Requirement: A routed model call may carry a reasoning effort
A request for a model chosen by the router, or by a `PERPLEXITY_TIER_*` pin in `dynamic` mode, SHALL carry `reasoning` with `effort` set to the level the router chose and SHALL carry none when it chose no level. A request for an explicit `model`, a configured model of `standard` or `custom` mode or a preset SHALL carry no `reasoning`. The body field `effort` (the preset name, see "The effort field means the preset name") and `reasoning.effort` (a model's level) SHALL stay distinct.

#### Scenario: Routed model with a level
- **WHEN** the router chooses a model with level `medium`
- **THEN** the request names the model and has `reasoning` `{"effort": "medium"}` and no top-level `effort` key

#### Scenario: Routed model with no level
- **WHEN** the router chooses a model that accepts no level
- **THEN** the request has no `reasoning` key

#### Scenario: Explicit model sends no reasoning
- **WHEN** a client asks with `model` `openai/gpt-6-luna` in `dynamic` mode
- **THEN** the request has no `reasoning` key

#### Scenario: Preset call
- **WHEN** a client asks with `depth` `low`
- **THEN** the request has top-level `effort` `low` and no `reasoning` key

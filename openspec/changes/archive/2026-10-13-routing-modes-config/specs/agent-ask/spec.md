## MODIFIED Requirements

### Requirement: Ask tool
The server SHALL provide `perplexity_ask`, a stateless synchronous tool that answers one `query` with web-grounded search. Its description SHALL state approximate costs per depth (fast about $0.001 to $0.002, low about $0.004 to $0.02, medium about $0.016 to $0.05), the active routing mode and the model a call with no selector uses, say that the default model's cost differs from the per-depth figures (the README and `perplexity_usage` give it), and say that it never waits for a background run. It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` false and `openWorldHint` true.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_ask` is present with typed parameters, an output schema, and a description naming the three costs, the mode and the default model

#### Scenario: Result validates
- **WHEN** an ask succeeds
- **THEN** its structured content validates against the advertised output schema and its text content carries the answer

### Requirement: Depth selects a preset
`depth` SHALL be `fast`, `low` or `medium` and selects the API preset of that name. A call that names no depth, tier or model SHALL NOT default to a preset: the routing mode supplies the model (see `routing-config`). `high` and `xhigh` SHALL be refused with `invalid_request` pointing to `perplexity_research`, because a run at those depths can last minutes and cost dollars.

#### Scenario: Default depth
- **WHEN** a client asks with no depth, no tier and no model
- **THEN** the request names the mode's default model (in `standard` mode with defaults, `perplexity/sonar`) and no preset

#### Scenario: Medium depth
- **WHEN** a client asks with depth `medium`
- **THEN** the request names preset `medium`

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

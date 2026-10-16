# Spec Delta

## MODIFIED Requirements

### Requirement: Depth selects a preset
`depth` SHALL be `fast`, `low` or `medium` and selects the API preset of that name. A call that names no depth, tier or model SHALL NOT default to a preset in `standard` and `custom` mode: the routing mode supplies the model (see `routing-config`); in `dynamic` mode the dynamic classifier may pick a tier that runs a preset. `high` and `xhigh` SHALL be refused with `invalid_request` pointing to `perplexity_research`, because a run at those depths can last minutes and cost dollars.

#### Scenario: Default depth
- **WHEN** a client asks with no depth, no tier and no model
- **THEN** in `standard` mode the request names the mode's default model (with defaults, `perplexity/sonar`) and no preset

#### Scenario: Medium depth
- **WHEN** a client asks with depth `medium`
- **THEN** the request names preset `medium`

#### Scenario: High depth refused
- **WHEN** a client asks with depth `high`
- **THEN** the call fails with `invalid_request` naming `perplexity_research` and no request reaches the API

### Requirement: Ask tool
The server SHALL provide `perplexity_ask`, a stateless synchronous tool that answers one `query` with web-grounded search. Its description SHALL state approximate costs per depth (fast about $0.001 to $0.002, low about $0.004 to $0.02, medium about $0.016 to $0.05), the active routing mode and what a call with no selector uses (the default model, or in `dynamic` mode the tier the server picks from the prompt), say that the default model's cost differs from the per-depth figures (the README and `perplexity_usage` give it), and say that it never waits for a background run. It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` false and `openWorldHint` true.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_ask` is present with typed parameters, an output schema, and a description naming the three costs, the mode and what a nameless call uses

#### Scenario: Result validates
- **WHEN** an ask succeeds
- **THEN** its structured content validates against the advertised output schema and its text content carries the answer

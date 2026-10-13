## MODIFIED Requirements

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
An explicit `model` SHALL replace the preset: the request names the model and no preset, grounds it with the web search tool and a step budget of 3, unless `search` is false, which sends no tools. `depth` together with `model`, or `tier` together with `model`, SHALL fail with `invalid_request`, and so SHALL `search` false without `model`, because a preset always searches. `search` true is always accepted.

#### Scenario: Model with search
- **WHEN** a client asks with model `openai/gpt-6-luna`
- **THEN** the request names that model and no preset, carries one web search tool and a step budget of 3

#### Scenario: Model without search
- **WHEN** a client asks with that model and `search` false
- **THEN** the request carries no tools and the result's sources are empty

#### Scenario: Conflicting options
- **WHEN** a client passes `depth` `low` together with a model, `tier` together with a model, or `search` false without a model
- **THEN** the call fails with `invalid_request` and no request reaches the API

#### Scenario: Search true is harmless
- **WHEN** a client passes `search` true with a depth and no model, or with a model
- **THEN** the request is the same as without `search`

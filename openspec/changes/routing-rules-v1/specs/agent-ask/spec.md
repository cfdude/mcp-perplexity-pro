# Spec Delta

## MODIFIED Requirements

### Requirement: Depth selects a preset
`depth` SHALL be `fast`, `low` or `medium` and selects the API preset of that name. A call that names no depth, tier or model SHALL NOT default to a preset in `standard` and `custom` mode: the routing mode supplies the model (see `routing-config`); in `dynamic` mode the rules may pick a tier that runs a preset. `high` and `xhigh` SHALL be refused with `invalid_request` pointing to `perplexity_research`, because a run at those depths can last minutes and cost dollars.

#### Scenario: Default depth
- **WHEN** a client asks with no depth, no tier and no model
- **THEN** in `standard` mode the request names the mode's default model (with defaults, `perplexity/sonar`) and no preset

#### Scenario: Medium depth
- **WHEN** a client asks with depth `medium`
- **THEN** the request names preset `medium`

#### Scenario: High depth refused
- **WHEN** a client asks with depth `high`
- **THEN** the call fails with `invalid_request` naming `perplexity_research` and no request reaches the API

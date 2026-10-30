# Spec Delta

## MODIFIED Requirements

### Requirement: Send takes the ask options
`send` SHALL accept the ask tool's `depth` (`fast`, `low` or `medium`), `tier`, `model`, `search`, search filters, `instructions` and `max_output_tokens` and apply the ask tool's rules and limits for them, except that it takes no `json_schema`. Each send may choose them anew, the model or tier included; the routing rules of `routing-config` apply to a send exactly as to an ask, and a send's result and stored message record the preset only when a preset ran (null for a model route).

#### Scenario: Depth per turn
- **WHEN** a first turn is sent at depth `fast` and the next at depth `low`
- **THEN** the second request has `effort` `low` while chaining from the first response

#### Scenario: Tier per turn
- **WHEN** a first turn is sent with `tier` `light` and the next with `tier` `complex` in `custom` mode
- **THEN** the second request names the `complex` tier's model while chaining from the first response

#### Scenario: Schema refused
- **WHEN** a client passes `json_schema` to a send
- **THEN** the call fails with `invalid_request`

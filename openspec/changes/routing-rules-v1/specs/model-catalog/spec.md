# Spec Delta

## ADDED Requirements

### Requirement: Active routing is reported in dynamic mode
In `dynamic` mode the `perplexity_models` routing section SHALL state mode `dynamic`, the classifier in use (`rules`), and the three tiers with what each resolves to: a preset name where the tier runs a preset, or a model id with `known` as in the other modes where it runs a model.

#### Scenario: Dynamic routing section
- **WHEN** a client calls `perplexity_models` against a server in `dynamic` mode with no tier variables set
- **THEN** the routing section has mode `dynamic`, classifier `rules`, `light` as preset `fast`, `standard` as model `perplexity/sonar` with `known`, and `complex` as preset `medium`

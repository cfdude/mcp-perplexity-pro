# Spec Delta

## ADDED Requirements

### Requirement: The routing section names the Decisions classifier
In `dynamic` mode with the Decisions classifier the `perplexity_models` routing section SHALL name classifier `decisions` and the decider model it asks, in place of `rules`.

#### Scenario: Decisions classifier section
- **WHEN** a client calls `perplexity_models` against a `dynamic` server with the Decisions classifier
- **THEN** the routing section names classifier `decisions` and the default decider model

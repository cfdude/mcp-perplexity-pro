# Spec Delta

## ADDED Requirements

### Requirement: Dynamic mode configuration
In `dynamic` mode `PERPLEXITY_MODEL`, `PERPLEXITY_TIER_LIGHT`, `PERPLEXITY_TIER_STANDARD` and `PERPLEXITY_TIER_COMPLEX` SHALL all be optional: the tier variables replace a tier's default, and a startup with none of them set SHALL succeed. The configuration rules of "Routing mode" and the model-id rules of `routing-config` apply to each variable that is set and used.

#### Scenario: Nothing set
- **WHEN** the server starts with `PERPLEXITY_ROUTING=dynamic` and only the API key
- **THEN** startup succeeds with the default tiers

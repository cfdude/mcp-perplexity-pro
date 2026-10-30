# Spec Delta

## MODIFIED Requirements

### Requirement: Dynamic mode configuration
In `dynamic` mode `PERPLEXITY_TIER_LIGHT`, `PERPLEXITY_TIER_STANDARD` and `PERPLEXITY_TIER_COMPLEX` SHALL all be optional (each pins that tier's calls to a model) and `PERPLEXITY_MODEL` SHALL be ignored with one warning; a startup with none of them set SHALL succeed. The configuration rules of "Routing mode" and the model-id rules of `routing-config` apply to each variable that is set and used.

#### Scenario: Nothing set
- **WHEN** the server starts with `PERPLEXITY_ROUTING=dynamic` and only the API key
- **THEN** startup succeeds and the router chooses the model of every nameless call

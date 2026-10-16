# Spec Delta

## ADDED Requirements

### Requirement: The classifier variable
`PERPLEXITY_CLASSIFIER` SHALL be an optional configuration variable (default `rules`) read with the other `PERPLEXITY_` variables and validated at startup as `routing-config` "The classifier setting" says.

#### Scenario: Default
- **WHEN** the server starts with only the API key
- **THEN** the classifier setting is `rules`

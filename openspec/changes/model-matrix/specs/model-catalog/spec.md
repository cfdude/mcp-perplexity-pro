# Spec Delta

## ADDED Requirements

### Requirement: The model list reports each model's efforts
`perplexity_models` SHALL give each listed model its effort facts from the matrix (`accepted`, `refused` and whether they were probed or come from the baseline) and SHALL include the matrix's provenance: its source (`file` or `baseline`), when it was last fetched, and how many models are still unprobed. A model not yet in the matrix SHALL be listed without efforts.

#### Scenario: Efforts shown
- **WHEN** a client calls `perplexity_models` against a server whose matrix holds `openai/gpt-5-nano` with `xhigh` and `max` refused
- **THEN** that model's entry lists its accepted levels and the two refused ones

#### Scenario: A model the matrix lacks
- **WHEN** the live list holds an id the matrix does not yet hold
- **THEN** it is listed with no efforts and counted as unprobed

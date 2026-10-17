# Spec Delta

## ADDED Requirements

### Requirement: The model list reports each model's efforts
`perplexity_models` SHALL give each listed model its effort facts from the matrix (`accepted` and `refused` as lists of levels, and their source) and SHALL include a `matrix` object: its `origin` (`file` or `baseline`), when it was last fetched, and how many `available` matrix models are `unprobed`. A model not in the matrix SHALL be listed without efforts. The facts are those stored; `refresh` on this tool refreshes the catalog list, not the matrix.

#### Scenario: Efforts shown
- **WHEN** a client calls `perplexity_models` against a server whose matrix holds `openai/gpt-5-nano` with `xhigh` and `max` refused
- **THEN** that model's entry lists its accepted levels and the two refused ones

#### Scenario: A model the matrix lacks
- **WHEN** the live list holds an id the matrix does not yet hold
- **THEN** it is listed with no efforts, and the `unprobed` count (which counts `available` matrix rows, not listed ids) is unchanged

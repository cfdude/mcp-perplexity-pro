# Spec Delta

## ADDED Requirements

### Requirement: The preset table follows the documentation
The documented presets in `perplexity_models` SHALL be those of Perplexity's documentation as of the date the result states: at the date the result states (2026-10-29 when this change shipped) `fast`, `low` and `medium` map to `openai/gpt-6-luna`, `high` to `openai/gpt-6.1-terra` and `xhigh` to `anthropic/claude-opus-5-5`. The result says the table comes from the documentation and not the live API, and that Perplexity manages the presets (they carry versions such as `fast@2026-10-16.0`).

#### Scenario: High maps to the current model
- **WHEN** a client calls `perplexity_models`
- **THEN** its preset table lists `high` with `openai/gpt-6.1-terra` and states `as_of` `2026-10-29`

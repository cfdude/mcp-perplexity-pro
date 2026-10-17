# Spec Delta

## ADDED Requirements

### Requirement: A background request is recorded under its module
Notwithstanding the rules that name the MCP tool, a project and a calling tool, a costed request made by a background task of the server (the matrix probe), with no tool call behind it, SHALL be recorded as its own usage event whose tool is `model_matrix`, whose project is none and whose API family is the request's own, so its spend is visible in `perplexity_usage` and a lower bound is not silently lost.

#### Scenario: No project is created
- **WHEN** a probe request is recorded
- **THEN** no project row is created or touched and `perplexity_usage` reports the event under no project

#### Scenario: A probe request
- **WHEN** the matrix probe sends one request that the API answers
- **THEN** one usage event exists with tool `model_matrix`, API `agent` and no project

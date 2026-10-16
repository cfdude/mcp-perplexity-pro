# Spec Delta

## ADDED Requirements

### Requirement: A nested request is recorded under its caller's tool
A costed request that a tool makes on behalf of another tool's call, such as the routing classification a `perplexity_ask` call triggers, SHALL be recorded as its own event whose tool is the name of the MCP tool the client called and whose API family is the request's own.

#### Scenario: Ask with a Decisions classification
- **WHEN** one `perplexity_ask` call triggers one Decisions classification
- **THEN** two events exist, both with tool `perplexity_ask`, one with API `agent` and one with API `decisions`

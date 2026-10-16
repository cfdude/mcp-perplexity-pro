# Spec Delta

## MODIFIED Requirements

### Requirement: One code path with the tools
Every command except `help` SHALL call the registered tool in-process, so routing resolution, validation, project rules, usage recording and error categories are those of the MCP tool. A costed command SHALL record one usage event per upstream request its call makes (one for an ask, two for an ask in `dynamic` mode with the Decisions classifier), in the same database the server uses.

#### Scenario: A costed command
- **WHEN** `perplexity-pro ask "q"` completes against a mocked upstream
- **THEN** exactly one usage event exists with tool `perplexity_ask` and the routing mode's default model

#### Scenario: Routing applies
- **WHEN** the environment sets `PERPLEXITY_ROUTING=custom` with three tiers and a user runs `perplexity-pro ask "q" --tier light`
- **THEN** the call names the light tier's model, as over MCP

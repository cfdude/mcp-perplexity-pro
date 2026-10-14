## MODIFIED Requirements

### Requirement: The instructions text
The MCP `instructions` SHALL be rendered at startup from the settings and state the mode, the standard model or the three tiers with their model ids, when to pass `tier`, `depth` or `model`, that depth `high` and `xhigh` belong to `perplexity_research`, and that `perplexity_help` explains the tools. The text SHALL contain no secret and SHALL be identical for the life of the process. `perplexity_help` repeats the routing mode but is a pointer and a topic, not a fifth channel of "The calling agent is told the configuration".

#### Scenario: Standard instructions
- **WHEN** a client initializes against a `standard` server
- **THEN** the instructions name the mode `standard` and the standard model, and do not mention tiers as usable

#### Scenario: Custom instructions
- **WHEN** a client initializes against a `custom` server
- **THEN** the instructions list `light`, `standard` and `complex` with their model ids and say that `tier` selects one

#### Scenario: Instructions point to help
- **WHEN** a client initializes against any server
- **THEN** the instructions name `perplexity_help`

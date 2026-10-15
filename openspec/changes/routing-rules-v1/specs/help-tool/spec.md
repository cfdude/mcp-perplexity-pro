# Spec Delta

## ADDED Requirements

### Requirement: The routing topic describes dynamic mode
On a `dynamic` server the `routing` topic SHALL state the mode, that the server picks a tier from the prompt when a call names nothing, the model or preset each tier runs, that `tier`, `depth` or `model` overrides the choice and that an explicit `model` is always used as given, and that the result's `routing` says which tier was picked and why. The topic keeps its 3000-byte limit.

#### Scenario: Dynamic routing topic
- **WHEN** a client asks for topic `routing` on a `dynamic` server
- **THEN** the text names the three tiers with what they run, says how to override, and is at most 3000 bytes

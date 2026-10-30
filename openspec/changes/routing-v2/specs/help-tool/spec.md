# Spec Delta

## MODIFIED Requirements

### Requirement: The index and routing topic describe dynamic mode
On a `dynamic` server the `index` routing line SHALL state mode `dynamic` and that the server picks a model and an effort from the prompt, within the existing 1500-byte limit, and the `routing` topic SHALL state the mode, which tiers are pinned to a model, that `tier`, `depth` or `model` overrides the choice, that an explicit `model` is always used as given, and that the result's `routing` says which model, effort and tier were picked and why. The topic keeps its 3000-byte limit.

#### Scenario: Dynamic index
- **WHEN** a client asks for the index of a `dynamic` server
- **THEN** it states mode `dynamic` and that the model and effort are picked from the prompt, and is at most 1500 ASCII bytes

#### Scenario: Dynamic routing topic
- **WHEN** a client asks for topic `routing` on a `dynamic` server
- **THEN** the text says the model and effort are picked from benchmark evidence and price, names any pinned tier, says how to override, and is at most 3000 bytes

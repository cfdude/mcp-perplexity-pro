# Spec Delta

## ADDED Requirements

### Requirement: The classifier setting
The server SHALL read `PERPLEXITY_CLASSIFIER` (case-insensitive), `rules` (the default) or `decisions`, and use it in `dynamic` mode only. In any other mode it SHALL be ignored with one warning naming the variable. An unknown value SHALL fail startup naming the variable and the two accepted values.

#### Scenario: Default classifier
- **WHEN** the server starts in `dynamic` mode with `PERPLEXITY_CLASSIFIER` unset
- **THEN** the rules classify

#### Scenario: Decisions classifier
- **WHEN** the server starts in `dynamic` mode with `PERPLEXITY_CLASSIFIER=decisions`
- **THEN** it starts and nameless calls are classified by the Decisions classifier

#### Scenario: Unused in other modes
- **WHEN** the server starts in `standard` mode with `PERPLEXITY_CLASSIFIER=decisions`
- **THEN** it starts, ignores the variable and logs one warning naming it

#### Scenario: Unknown value
- **WHEN** `PERPLEXITY_CLASSIFIER=smart`
- **THEN** startup fails naming `PERPLEXITY_CLASSIFIER` and the accepted values

### Requirement: The routing result names the classifier
When the tier was picked by a classifier (`selected_by` `rules`), the `routing` object of an ask or chat result SHALL carry `classifier`, `rules` or `decisions`: `decisions` only when the Decisions answer decided the tier, `rules` otherwise, including when the rules replaced a failed or weak answer. In every other case `classifier` is null.

#### Scenario: Decisions decided
- **WHEN** the Decisions classifier answers with confidence 0.9
- **THEN** the routing carries `classifier` `decisions` and a reason naming the tier and the confidence

#### Scenario: Fallback
- **WHEN** the Decisions request times out
- **THEN** the routing carries `classifier` `rules` and a reason naming the timeout

#### Scenario: Explicit selector
- **WHEN** a call names `tier`
- **THEN** the routing's `classifier` is null

### Requirement: The classifier is told to the calling agent
In `dynamic` mode the MCP `instructions` and the ask and chat description sentence SHALL name the classifier in use and, for `decisions`, that the rules replace it when it is unavailable.

#### Scenario: Decisions instructions
- **WHEN** a client initializes against a `dynamic` server with the Decisions classifier
- **THEN** the instructions name the Decisions classifier and its fallback to the rules

# Spec Delta

## ADDED Requirements

### Requirement: The classifier setting
The server SHALL read `PERPLEXITY_CLASSIFIER` (case-insensitive), `rules` (the default) or `decisions`, and use it in `dynamic` mode only. In any other mode it SHALL be ignored with one warning naming the variable and not validated. An unknown value in `dynamic` mode SHALL fail startup naming the variable and the two accepted values.

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
- **WHEN** `PERPLEXITY_CLASSIFIER=smart` in `dynamic` mode
- **THEN** startup fails naming `PERPLEXITY_CLASSIFIER` and the accepted values

#### Scenario: Unknown value in another mode
- **WHEN** `PERPLEXITY_CLASSIFIER=smart` in `standard` mode
- **THEN** the server starts and logs one warning naming the variable

### Requirement: The classifier field can be decisions
Where `routing-config` says the `routing` object's `classifier` is the classifier that decided, its value SHALL be `decisions` or `rules` when the Decisions classifier is configured, as defined by "The classifier field says who supplied the tier" in `routing-decisions-classifier`, and null whenever `selected_by` is not `classifier`.

#### Scenario: Explicit selector
- **WHEN** a call in this mode names `tier`
- **THEN** the routing's `classifier` is null

### Requirement: The classifier is told to the calling agent
In `dynamic` mode the MCP `instructions` and the ask and chat description sentence SHALL name the classifier in use and, for `decisions`, that the rules replace it when it is unavailable.

#### Scenario: Decisions instructions
- **WHEN** a client initializes against a `dynamic` server with the Decisions classifier
- **THEN** the instructions name the Decisions classifier and its fallback to the rules

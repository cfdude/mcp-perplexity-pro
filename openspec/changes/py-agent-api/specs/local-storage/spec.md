# Spec Delta

## MODIFIED Requirements

### Requirement: Project resolution
Every stored record SHALL belong to a named project, except retained records. One shared get-or-create SHALL resolve the project for every tool call that stores records: it creates the project when first named and uses `default` when none is given. `perplexity_projects`, tools without a project argument and by-id actions (chat send with `chat_id`, chat read, delete, list, every `perplexity_jobs` action) look it up instead and fail `not_found` if absent (a list returns nothing).

#### Scenario: Implicit creation
- **WHEN** a tool is called with a project name that does not yet exist
- **THEN** the project is created and the call proceeds

#### Scenario: Default project
- **WHEN** a tool is called without a project name
- **THEN** the record belongs to the project `default`, which is created if absent

#### Scenario: Delete with an invalid name
- **WHEN** a client calls `delete` with project `../etc` and `confirm` true
- **THEN** the call fails with category `invalid_request`

#### Scenario: By-id action in an absent project
- **WHEN** a chat is read, or a job's status is requested, naming a project that does not exist
- **THEN** the call fails with `not_found` and the project still does not exist

### Requirement: All-or-nothing tool calls
A tool's own writes SHALL be one unit of work; a call observing several background runs commits each observation in its own unit. No write unit SHALL stay open across an upstream call; project resolution may commit first and survives a later failure. Usage recording runs in its own unit while the caller holds no write unit. A failed call leaves none of its own writes except committed observations (a later failure removes only the failing observation's writes) and its usage event.

#### Scenario: Failure after a write
- **WHEN** a tool writes a record and then fails before returning
- **THEN** the record is not present afterwards

#### Scenario: Usage event outlives the failure
- **WHEN** a tool makes a costed upstream call, writes a record and then fails before returning
- **THEN** the record is not present afterwards and the usage event for the upstream call is

#### Scenario: Write lock not held across the call
- **WHEN** a tool makes an upstream call that takes longer than the busy timeout while another call tries to write
- **THEN** the other write succeeds, because the tool holds no write unit of work during the call

#### Scenario: Several observations, one fails
- **WHEN** a call observes three background runs and the second observation's row update fails
- **THEN** the first and third observations remain committed, the second observation's row changes are gone and its usage event remains

Scenarios in this capability that need a writing tool are verified with a tool registered only by the test, built through the same server factory as production; no production tool is required to write for them to pass.

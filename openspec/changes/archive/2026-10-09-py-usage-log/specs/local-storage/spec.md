## ADDED Requirements

### Requirement: Retained records
A table that references `projects` with a foreign key declared `ON DELETE SET NULL` holds retained records, and SHALL also keep its own copy of the project name. Every other table that references `projects` directly holds ordinary records. A table added later joins one group or the other by how its foreign key is declared, with no change to project deletion.

#### Scenario: New retained table
- **WHEN** a table added by a later change references `projects` with `ON DELETE SET NULL` and a project owning its rows is deleted
- **THEN** those rows are detached, not deleted, without any change to the deletion code

#### Scenario: New ordinary table
- **WHEN** a table added by a later change references `projects` with `ON DELETE CASCADE` and a project owning its rows is deleted
- **THEN** those rows are removed and counted, without any change to the deletion code

### Requirement: Deleting a project keeps retained records
Deleting a project SHALL NOT delete retained records. It SHALL detach them, clearing their project reference, in the same transaction that removes the project and its ordinary records, and SHALL report how many were detached.

#### Scenario: Retained records detached
- **WHEN** a project that owns 3 retained records and 2 ordinary records is deleted with `confirm` true
- **THEN** the 2 ordinary records are gone, the 3 retained records remain with no project reference and their project name, and the result reports `rows_removed` 2 and `rows_retained` 3

#### Scenario: Detach is all-or-nothing
- **WHEN** deleting a project fails after its retained records were detached
- **THEN** the retained records still reference the project and the project still exists

## MODIFIED Requirements

### Requirement: Project resolution
Every stored record SHALL belong to a named project, except retained records, which may belong to none. One shared get-or-create operation SHALL resolve the project for every tool call that stores records: it creates the project the first time it is named and uses the project `default` when none is given. `perplexity_projects` and tools that take no project argument do not call it; `list` and `delete` look projects up and never create them. Tools added by later changes inherit these rules.

#### Scenario: Implicit creation
- **WHEN** a tool is called with a project name that does not yet exist
- **THEN** the project is created and the call proceeds

#### Scenario: Default project
- **WHEN** a tool is called without a project name
- **THEN** the record belongs to the project `default`, which is created if absent

### Requirement: Project management tool
The server SHALL provide a tool `perplexity_projects` with actions `list` and `delete`. `delete` takes a `project` name, removes the project and its non-retained records in one transaction, and SHALL require `confirm` set to true. A successful `delete` returns the project name, the rows removed from tables that reference the project directly (`rows_removed`) and the number of retained records detached (`rows_retained`); rows in deeper tables go by cascade and are not counted.

#### Scenario: Listing
- **WHEN** a client calls the tool with action `list`
- **THEN** the result contains each project name with its creation time

#### Scenario: Delete without confirmation
- **WHEN** a client calls `delete` without `confirm` true
- **THEN** the call fails with category `confirmation_required` and nothing is removed

#### Scenario: Confirmed delete
- **WHEN** a client calls `delete` with `confirm` true for an existing project
- **THEN** the project and all of its records other than retained ones are gone and a following `list` omits it

### Requirement: All-or-nothing tool calls
A tool's own writes SHALL happen in one unit of work. A tool SHALL NOT hold a write unit of work open across an upstream call; project resolution may commit before one and its project then survives a later failure. Usage recording runs in its own unit of work, invoked while the caller holds no write unit on that engine. If the call fails, none of the tool's own writes SHALL remain; a usage event recorded for the failed call does.

#### Scenario: Failure after a write
- **WHEN** a tool writes a record and then fails before returning
- **THEN** the record is not present afterwards

#### Scenario: Usage event outlives the failure
- **WHEN** a tool makes a costed upstream call, writes a record and then fails before returning
- **THEN** the record is not present afterwards and the usage event for the upstream call is

#### Scenario: Write lock not held across the call
- **WHEN** a tool makes an upstream call that takes longer than the busy timeout while another call tries to write
- **THEN** the other write succeeds, because the tool holds no write unit of work during the call

Scenarios in this capability that need a writing tool are verified with a tool registered only by the test, built through the same server factory as production; no production tool is required to write for them to pass.

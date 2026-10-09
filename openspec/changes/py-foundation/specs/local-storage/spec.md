# Spec Delta

## Purpose

Defines how the server keeps its own data on disk: where it lives, how its schema evolves, how records are grouped by project, and how concurrent calls and failures leave it consistent.

## ADDED Requirements

### Requirement: Single local database
The server SHALL keep all persistent data in one SQLite database file under a configurable data directory (default `~/.perplexity-pro/`), creating the directory and file on first start. It SHALL NOT write into the working directory of the calling project.

#### Scenario: First start
- **WHEN** the server starts and the data directory does not exist
- **THEN** the directory and the database file are created and the server reaches ready state

#### Scenario: Project directory untouched
- **WHEN** a tool runs while the server's working directory is a project repository
- **THEN** no `.perplexity` directory or other new file appears in that repository

### Requirement: Owner-only access
The data directory SHALL be created readable and writable by its owner only, and the API key SHALL NOT be stored in it.

#### Scenario: Directory permissions
- **WHEN** the data directory is created
- **THEN** its permission bits allow no access to group or others

#### Scenario: Existing loose directory
- **WHEN** the server starts and the data directory already exists with group or other access
- **THEN** the permissions are tightened to owner-only, or startup fails naming the directory

### Requirement: Versioned migrations
The database schema SHALL be managed by ordered migrations named with a four-digit sequence prefix. The server SHALL apply pending migrations to the latest version at startup and SHALL refuse to start, with a clear message, if a migration fails or the database is newer than the code. Every migration SHALL be reversible.

#### Scenario: Fresh database
- **WHEN** the server starts against an empty database
- **THEN** all migrations are applied and the recorded schema version equals the latest

#### Scenario: Failing migration
- **WHEN** a pending migration raises an error
- **THEN** startup fails with a message naming the migration, the database keeps its previous schema and rows, and, if the database was non-empty, the pre-migration backup exists

#### Scenario: Two processes start together
- **WHEN** two server processes start at the same moment against one data directory
- **THEN** exactly one applies the migrations, the other waits and proceeds, and both reach ready state

#### Scenario: Database from the future
- **WHEN** the database records a version the code does not know
- **THEN** startup fails with a message naming both versions and the schema and rows are unchanged

#### Scenario: Downgrade
- **WHEN** the latest migration is reversed
- **THEN** the schema returns to the previous version with earlier data intact

### Requirement: Backup before migrating
Before applying pending migrations to a database that has a recorded schema revision, the server SHALL copy the database file to a backup in the data directory named with the schema revision it came from.

#### Scenario: Backup exists after upgrade
- **WHEN** a non-empty database at revision `0001` is upgraded
- **THEN** a backup file for revision `0001` exists in the data directory and opens with the old schema

### Requirement: Project resolution
Every stored record SHALL belong to a named project. One shared get-or-create operation SHALL resolve the project for every tool call that stores records: it creates the project the first time it is named and uses the project `default` when none is given. `perplexity_projects` and tools that take no project argument do not call it; `list` and `delete` look projects up and never create them. Tools added by later changes inherit these rules.

#### Scenario: Implicit creation
- **WHEN** a tool is called with a project name that does not yet exist
- **THEN** the project is created and the call proceeds

#### Scenario: Default project
- **WHEN** a tool is called without a project name
- **THEN** the record belongs to the project `default`, which is created if absent

### Requirement: Project names
Project names are case-sensitive and unique, limited to ASCII letters, digits, `-`, `_` and `.`, up to 64 characters, and SHALL NOT be `.`, `..`, begin with `.` or be shaped like an API key (`pplx-` followed by 20 or more key characters).

#### Scenario: Invalid name
- **WHEN** a tool is called with project name `../etc`
- **THEN** the call fails with category `invalid_request` and no project is created

#### Scenario: Key-shaped name rejected
- **WHEN** a tool is called with a project name of the form `pplx-` followed by 24 letters
- **THEN** the call fails with category `invalid_request` and no project is created

#### Scenario: Dot names rejected
- **WHEN** a tool is called with project name `..` or `.hidden`
- **THEN** the call fails with category `invalid_request`

### Requirement: Project management tool
The server SHALL provide a tool `perplexity_projects` with actions `list` and `delete`. `delete` takes a `project` name, removes the project and all its records in one transaction, and SHALL require `confirm` set to true. A successful `delete` returns the project name and the number of rows removed from tables that reference the project directly; rows in deeper tables are removed by cascade and are not counted.

#### Scenario: Listing
- **WHEN** a client calls the tool with action `list`
- **THEN** the result contains each project name with its creation time

#### Scenario: Delete without confirmation
- **WHEN** a client calls `delete` without `confirm` true
- **THEN** the call fails with category `confirmation_required` and nothing is removed

#### Scenario: Confirmed delete
- **WHEN** a client calls `delete` with `confirm` true for an existing project
- **THEN** the project and all of its records are gone and a following `list` omits it

### Requirement: Project deletion outcomes
`delete` SHALL validate the project name by the project-name rule and SHALL fail with category `invalid_request` for a bad name and `not_found` for a project that does not exist. Deleting the project `default` is allowed; it is recreated on next use.

#### Scenario: Delete a missing project
- **WHEN** a client calls `delete` with `confirm` true for a project that does not exist
- **THEN** the call fails with category `not_found`

#### Scenario: Delete with an invalid name
- **WHEN** a client calls `delete` with project `../etc` and `confirm` true
- **THEN** the call fails with category `invalid_request`

### Requirement: All-or-nothing tool calls
Each tool call SHALL read and write the database as one unit of work. If the call fails, none of its writes SHALL remain.

#### Scenario: Failure after a write
- **WHEN** a tool writes a record and then fails before returning
- **THEN** the record is not present afterwards

Scenarios in this capability that need a writing tool are verified with a tool registered only by the test, built through the same server factory as production; no production tool is required to write for them to pass.

### Requirement: Concurrent calls
Concurrent tool calls SHALL NOT corrupt the database or fail with lock errors under normal load. A write that must wait for another SHALL wait up to the configured busy timeout and then fail with category `storage_busy`.

#### Scenario: Writer holds the lock too long
- **WHEN** one connection holds the write lock beyond the busy timeout and another call tries to write
- **THEN** the waiting call fails with category `storage_busy`

#### Scenario: Parallel writes
- **WHEN** 20 tool calls that write to the database run at the same time
- **THEN** all 20 succeed and all 20 records are present

# Spec Delta

## Purpose

Defines the checks that every change must pass before it is committed or merged, and the rules for tests and recorded API data, so the repository stays clean without relying on anyone remembering to run them.

## ADDED Requirements

### Requirement: Pre-commit enforcement
A commit SHALL be rejected when ruff linting reports an error, when ruff formatting would change any staged Python file, or when the test suite fails. Ruff SHALL apply safe auto-fixes and formatting before checking.

#### Scenario: Lint error
- **WHEN** a commit stages a file containing an undefined name, which ruff cannot fix automatically
- **THEN** the commit is rejected and the ruff message is shown

#### Scenario: Failing test
- **WHEN** a commit is attempted while one test fails
- **THEN** the commit is rejected and the failing test is shown

#### Scenario: Clean commit
- **WHEN** all staged files are formatted, lint-clean and all tests pass
- **THEN** the commit succeeds

### Requirement: Single tool per job
Syntax checking, linting and formatting SHALL each be done by ruff and by no other tool. Line length SHALL be 100. No wrapper script SHALL stand in for the ruff commands in the hook or in CI.

#### Scenario: Configuration
- **WHEN** the project configuration is read
- **THEN** ruff is configured with line length 100 and no second formatter or linter is configured

### Requirement: CI runs the same checks
Continuous integration SHALL run the same ruff and pytest checks on every push and pull request, from the committed lockfile, and SHALL fail the run when any check fails.

#### Scenario: Pull request with a failing test
- **WHEN** a pull request contains a failing test
- **THEN** the CI run is marked failed

#### Scenario: Interpreter matrix
- **WHEN** CI runs
- **THEN** the same checks run on Python 3.12 and Python 3.14

### Requirement: Reproducible dependencies
Dependency versions SHALL be pinned by a committed lockfile. CI SHALL install with lock-asserting semantics: the install fails if the lockfile does not match the project file and never re-resolves.

#### Scenario: Lockfile out of date
- **WHEN** a dependency is changed in the project file without updating the lockfile
- **THEN** the CI install step fails and the lockfile is not modified

### Requirement: Built package is self-contained
The built wheel SHALL contain everything needed to start the server, including database migrations.

#### Scenario: Wheel in a clean environment
- **WHEN** the wheel is installed into a fresh virtual environment and started with a dummy API key and a temporary data directory
- **THEN** it creates and migrates the database and answers `GET /health` with 200

### Requirement: Tests are offline by default
Tests SHALL live under `tests/` and SHALL make no network call by default. Tests that call the real Perplexity API SHALL be marked `live` and SHALL run only when explicitly selected.

#### Scenario: Default run
- **WHEN** the test suite runs with no network access and no `PERPLEXITY_API_KEY` in the environment
- **THEN** every unmarked test passes (tests inject a dummy key through settings) and every `live` test is deselected

#### Scenario: Live run
- **WHEN** the suite is run selecting the `live` marker with a valid key
- **THEN** the live tests execute against the real API

### Requirement: Recorded API fixtures
API response fixtures SHALL be saved under `tests/fixtures/` with the capture date and endpoint recorded, SHALL have credentials and account identifiers removed, and SHALL come from real calls, not hand-written approximations.

#### Scenario: Fixture hygiene
- **WHEN** the fixture directory is scanned
- **THEN** no file contains a string matching the API key format and each fixture records its endpoint and capture date

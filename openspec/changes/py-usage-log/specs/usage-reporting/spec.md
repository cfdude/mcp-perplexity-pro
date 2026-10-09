# usage-reporting Specification

## Purpose

Defines the read-only tool that reports what upstream Perplexity calls have cost, from the recorded usage events: exact totals and one grouping, filtered by project and date range, so spend is visible without reading the database.

## ADDED Requirements

### Requirement: Spend report tool
The server SHALL provide a tool `perplexity_usage` that reports recorded usage. It SHALL be declared read-only, SHALL never write to the database or create a project, and SHALL return structured content that validates against its advertised output schema, together with a plain-text rendering.

#### Scenario: Empty history
- **WHEN** a client calls `perplexity_usage` with no arguments and no events exist
- **THEN** the result has zero calls, zero cost and no groups, and is not an error

#### Scenario: Read-only
- **WHEN** a client calls `perplexity_usage`
- **THEN** the tool is advertised as read-only and no row is added, changed or removed

#### Scenario: Output schema
- **WHEN** a client calls `perplexity_usage` over MCP
- **THEN** the structured content validates against the advertised output schema

### Requirement: Report filters
`perplexity_usage` SHALL accept an optional `project` (default: all projects) and optional `since` and `until` ISO dates read as UTC days: `since` includes the whole of its day and `until` includes the whole of its day. A malformed date, a `since` after `until` or an invalid project name SHALL fail with category `invalid_request`. A project with no events, or one that has been deleted, SHALL report normally.

#### Scenario: Date bounds inclusive
- **WHEN** events exist at 2026-10-07 23:59:59 UTC and 2026-10-08 00:00:00 UTC and `since` and `until` are both `2026-10-08`
- **THEN** only the second event is counted

#### Scenario: Bad dates
- **WHEN** `since` is `2026-13-01`, or `since` is `2026-10-09` and `until` is `2026-10-01`
- **THEN** the call fails with category `invalid_request`

#### Scenario: Deleted project still reportable
- **WHEN** a project has been deleted and `project` names it
- **THEN** the result holds that project's events, not an error

#### Scenario: Unknown project
- **WHEN** `project` names a project that never existed
- **THEN** the result has zero calls and no project is created

### Requirement: Exact totals
The result SHALL include totals over every matching event, independent of grouping and limit: the number of calls, the number of calls whose status is not `ok`, input, output and total tokens (unknown counts add 0), the cost as an integer in nano-USD and as an exact decimal USD string, the number of calls whose cost is `computed` and the number of successful calls whose cost is `none`.

#### Scenario: Exact sum
- **WHEN** three matching events cost 210000, 20000 and 1000000 nano-USD
- **THEN** the total cost is 1230000 nano-USD and the USD string is `0.00123`

#### Scenario: Errors counted
- **WHEN** two of five matching events have a status other than `ok`
- **THEN** the totals report 5 calls and 2 errors

#### Scenario: Unpriced calls disclosed
- **WHEN** a successful event has cost source `none`
- **THEN** the totals count it among calls with unknown cost, so the cost total is visibly a lower bound

### Requirement: Grouping
`perplexity_usage` SHALL accept one `group_by` value from `tool`, `api`, `model`, `project` and `day` (default `tool`). Each group SHALL carry its key and the same measures as the totals. An event with no value for the grouped field SHALL appear under the key `(none)`; the key for `day` is the UTC date as `YYYY-MM-DD`.

#### Scenario: Group by project
- **WHEN** events exist for projects `alpha` and `beta` and `group_by` is `project`
- **THEN** one group per project name is returned with that project's calls and cost

#### Scenario: Deleted project's history
- **WHEN** a project was deleted and `group_by` is `project`
- **THEN** its events are grouped under its original name

#### Scenario: Group by day
- **WHEN** events span three UTC days and `group_by` is `day`
- **THEN** three groups are returned in date order, each keyed `YYYY-MM-DD`

#### Scenario: Missing value
- **WHEN** an event has no model and `group_by` is `model`
- **THEN** it is counted under the key `(none)`

#### Scenario: Invalid grouping
- **WHEN** `group_by` is `colour`
- **THEN** the call fails with category `invalid_request`

### Requirement: Group ordering and limit
Groups SHALL be ordered by cost descending then key, except `day`, which is ordered by date ascending. `perplexity_usage` SHALL accept a `limit` on the number of groups returned (default 20, at most 200). When groups are cut by the limit, the result SHALL say so and give the number of groups in all.

#### Scenario: Limit
- **WHEN** five groups match and `limit` is 2
- **THEN** two groups are returned, the result says groups were cut, and the totals still cover all five

#### Scenario: Limit out of range
- **WHEN** `limit` is 0 or 201
- **THEN** the call fails with category `invalid_request`

## MODIFIED Requirements

### Requirement: Job records
Each started run SHALL be a row of `research_jobs` (migration `0004`, ids never reused) in its project: query, depth, response id, status, model, our own start and finish times, result text and sources, the usage summary (input, output and total tokens, cost, source), whether usage was recorded, when a cancel was requested and when the provider first did not know the run. The provider's `created_at` and `completed_at` SHALL NOT be stored: the API rewrites both on every fetch.

#### Scenario: Our own times
- **WHEN** a run is submitted and then fetched twice by `status`
- **THEN** the job's start time is the time of submission and does not change when the fetched snapshots carry different `created_at` values

#### Scenario: Migration up and down
- **WHEN** a revision-0003 database is upgraded to 0004, downgraded and upgraded again
- **THEN** the table is created with the backup named for revision 0003, dropped on downgrade with `projects`, `chats` and `usage_events` intact, and created again

#### Scenario: Live database upgrades straight to head
- **WHEN** a revision-0002 database holding rows is upgraded with the real migrations through revision 0004
- **THEN** it reaches revision 0004 in one run with exactly one backup, named for revision 0002, and no backup named for 0003

#### Scenario: Project deletion
- **WHEN** a project with 2 jobs is deleted with `confirm` true
- **THEN** the jobs are gone and counted in `rows_removed`, and usage events already recorded remain reportable by name

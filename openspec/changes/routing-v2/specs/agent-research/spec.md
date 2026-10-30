# Spec Delta

## MODIFIED Requirements

### Requirement: Research tool
The server SHALL provide `perplexity_research`, which starts a background run for one `query` (not blank, at most 20000 characters) and returns at once with a local `job_id`, the provider's `response_id`, the status the provider reported and the project. `depth` SHALL be optional with no default value in the tool's schema (null): an explicit `medium`, `high` or `xhigh` runs that preset in every mode; an omitted `depth` runs `medium` outside `dynamic` routing mode and is routed in `dynamic` mode (see "A nameless research run is routed in dynamic mode"). The command line front end SHALL show no default for `--depth`. `instructions` (at most 10000 characters) and `project` are optional. It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` false and `openWorldHint` true.

#### Scenario: Submit
- **WHEN** a client starts research with no depth in `standard` mode and the API returns the recorded queued response
- **THEN** the result has a `job_id`, the response id, `status` `queued` and depth `medium`, and a job row with that id exists for the project

#### Scenario: Explicit medium is a preset in dynamic mode
- **WHEN** a client starts research with depth `medium` in `dynamic` mode
- **THEN** the request names preset `medium` and no model

#### Scenario: Blank query
- **WHEN** a client starts research with a blank query
- **THEN** the call fails with `invalid_request`, no request reaches the API and no job or project is created

#### Scenario: Unknown depth
- **WHEN** a client passes depth `fast`
- **THEN** the call fails with `invalid_request` naming `perplexity_ask`

#### Scenario: The routed sentinel is not a depth
- **WHEN** a client passes depth `routed`
- **THEN** the call fails with `invalid_request` and no request reaches the API

#### Scenario: Where an omitted depth is decided
- **WHEN** a client omits `depth`
- **THEN** the tool resolves it (the default preset outside `dynamic` mode, the router in it) before the request is built, so the request builder never sees a null depth

#### Scenario: Schema and description
- **WHEN** a client lists the tools
- **THEN** the `depth` property of `perplexity_research` has no `default` other than null and its description says an omitted depth is `medium`, or the server's routed choice in `dynamic` mode

### Requirement: The model is known only from a finished run
A snapshot's `model` SHALL be stored and recorded only when the snapshot is `completed`, or when its value contains `/` and differs from the job's depth. The API reports the preset name (such as `medium`) as `model` on queued, in-progress and cancelled snapshots, and that is not a model. A routed job SHALL have its model set at submit to the model that was requested, and a `completed` snapshot's reported model SHALL replace it.

#### Scenario: Preset name is not a model
- **WHEN** a queued or in-progress snapshot reports model `medium` for a job of depth `medium`
- **THEN** the job's model stays empty

#### Scenario: Completed snapshot
- **WHEN** the recorded completed snapshot reports `openai/gpt-6-luna`
- **THEN** the job's model and the recorded event's model are `openai/gpt-6-luna`

#### Scenario: A routed job knows its model at submit
- **WHEN** a routed run is submitted with model `M` and its first snapshot is queued
- **THEN** the job's model is `M`, and a later completed snapshot reporting `M@v2` replaces it

### Requirement: Submit that returns another status
A submit whose status is terminal (`completed`, `failed`, `incomplete`, `cancelled`, or any status with a non-null `error`) SHALL create the job row as terminal with its result, be recorded once by the submit itself, and be stored with `usage_recorded` set so no later observation records it again. Any other status SHALL be stored verbatim (redacted, cut to 64 characters), as a running job, with no event. The event of a routed submit, finished or failed, SHALL have preset null, never `routed`.

#### Scenario: Run finished at submit
- **WHEN** a submit returns the recorded completed snapshot
- **THEN** the job is `completed` with its answer stored, exactly one event exists, and a later `status` neither fetches nor records

#### Scenario: Unknown submit status
- **WHEN** a submit returns status `paused`
- **THEN** the job row is stored with status `paused`, no event exists and no error is raised

#### Scenario: A routed run finished at submit
- **WHEN** a routed submit returns a completed snapshot
- **THEN** exactly one event exists with preset null, and the job row has depth `routed`

#### Scenario: A failed routed submit
- **WHEN** a routed submit fails with `rate_limited`
- **THEN** one event exists with status `rate_limited` and preset null, and no job row is stored

### Requirement: Job records
Each started run SHALL be a row of `research_jobs` (migration `0004`, ids never reused; `effort` added by migration `0006`) in its project: query, depth (the preset, or `routed` for a routed run), response id, status, model, the effort level sent for a routed run (null otherwise), our own start and finish times, result text and sources, the usage summary (input, output and total tokens, cost, source), whether usage was recorded, when a cancel was requested and when the provider first did not know the run. The provider's `created_at` and `completed_at` SHALL NOT be stored: the API rewrites both on every fetch.

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

### Requirement: Recording follows the recorder contract
A usage event for a job SHALL be recorded while no write unit is open, before the job row's own update, with the job's project name, preset equal to its depth (null for a routed job, whose depth is `routed` and is not a preset), and latency measured from the job's start to the observation. If the update fails after the event was recorded, a later call SHALL NOT record a second event for a run of any terminal status: it finds the event and writes only the row.

#### Scenario: Update fails after recording
- **WHEN** the job row's update fails after the event for a completed run was recorded, and the job is observed again
- **THEN** one event exists for that response id

#### Scenario: Cancelled run whose update failed
- **WHEN** the row update of a cancelled run fails once after its event was recorded, and the job is observed again
- **THEN** still one event exists for that response id and the second observation writes the row as `cancelled`

#### Scenario: A routed job has no preset
- **WHEN** a routed job is first observed finished
- **THEN** its event has preset null and the model the response reports

## ADDED Requirements

### Requirement: A nameless research run is routed in dynamic mode
In `dynamic` mode a research call with `depth` omitted SHALL be classified by the rules (never by the Decisions classifier) and routed like an ask under the research cap, and its background request SHALL name the chosen model with `reasoning.effort` when one was chosen and the web search tool. If the API refuses a background run for a named model, the tier's documented preset SHALL run instead (see `routing-evidence`, research fallback).

#### Scenario: Routed research
- **WHEN** a client starts research with no depth in `dynamic` mode and the router chooses model `M` with level `high`
- **THEN** the background request names `M`, has `reasoning.effort` `high`, `background` true and `store` true

#### Scenario: Named depth is a preset
- **WHEN** a client starts research with depth `xhigh` in `dynamic` mode
- **THEN** the request names preset `xhigh` and no model

#### Scenario: Not routed outside dynamic mode
- **WHEN** a client starts research with no depth in `custom` mode
- **THEN** the request names preset `medium`

#### Scenario: A pin applies to research
- **WHEN** `PERPLEXITY_TIER_COMPLEX` is set and a `complex` research prompt is routed
- **THEN** the pinned model runs with the research effort of the tier

#### Scenario: Xhigh is never automatic
- **WHEN** the router routes a `complex` research prompt
- **THEN** no level above `high` is sent

### Requirement: A routed job is shown as routed with its model and effort
`perplexity_research` and `perplexity_jobs` (list, status, result, cancel) SHALL show a routed job's depth as `routed` together with its `model` and `effort`, and their descriptions SHALL say that depth is a preset, or `routed`. The one-line text of a listed job SHALL name the model and effort.

#### Scenario: List
- **WHEN** a project has a routed job (model `M`, effort `high`) and a preset job
- **THEN** the list shows depth `routed`, model `M` and effort `high` for the first and depth `high` with null effort for the second

#### Scenario: Status
- **WHEN** a routed job is read with `status`
- **THEN** the result has depth `routed`, its model and its effort

### Requirement: A routed research job stores its level in its own column
A routed job SHALL store depth `routed` (the `depth` column is `NOT NULL`, and a sentinel avoids rebuilding the table), the level sent in a nullable `research_jobs.effort` column added by migration `0006`, and the routed model in `model`. Its usage event SHALL have preset null, a failed submit's included.

#### Scenario: Routed job row
- **WHEN** research is routed to model `M` with level `high`
- **THEN** the job row has depth `routed`, effort `high` and model `M`, and the result's depth is `routed`

#### Scenario: Preset job row
- **WHEN** research runs preset `high`
- **THEN** the job row has depth `high` and effort null, and its event preset is `high`

#### Scenario: A routed job is recorded without a preset
- **WHEN** a routed job is first observed finished
- **THEN** one usage event exists with preset null and the model the response reports

#### Scenario: Migration reversibility
- **WHEN** migration `0006` is downgraded
- **THEN** the `research_jobs` rows remain, the `effort` column is gone and `embedding_chunks` rows for jobs remain

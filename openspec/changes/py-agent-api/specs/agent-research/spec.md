# Spec Delta

## Purpose

Defines `perplexity_research` and `perplexity_jobs`: long research runs that execute in the background at the provider, the local job records that track them, and how their cost is recorded once the run reaches a terminal state, so that no tool call ever waits for a run to finish.

## ADDED Requirements

### Requirement: Research tool
The server SHALL provide `perplexity_research`, which starts a background run for one `query` and returns at once with a local `job_id`, the provider's `response_id`, the status the provider reported and the project. `depth` SHALL be `medium` (the default), `high` or `xhigh`; `instructions` and `project` are optional.

#### Scenario: Submit
- **WHEN** a client starts research at the default depth and the API returns the recorded queued response
- **THEN** the result has a job id, the response id, status `queued` and depth `medium`, and a job row exists for the project

#### Scenario: Blank query
- **WHEN** a client starts research with a blank query
- **THEN** the call fails with `invalid_request`, no request reaches the API and no job or project is created

#### Scenario: Unknown depth
- **WHEN** a client passes depth `fast`
- **THEN** the call fails with `invalid_request` naming `perplexity_ask`

### Requirement: Research cost is stated
The description of `perplexity_research` SHALL state that `medium` costs about $0.016 to $0.05, that `high` can cost up to about $0.4 to $0.9 and `xhigh` more (estimates, not measured by this server), and that results are read with `perplexity_jobs`.

#### Scenario: Description
- **WHEN** a client lists the tools
- **THEN** the description of `perplexity_research` names the `medium` and `high` cost ranges and `perplexity_jobs`

### Requirement: Runs are background and retrievable
Every research request SHALL set `background` true and `store` true, and the tool SHALL offer no way to set `store` false: the API makes a background run with `store` false unretrievable, so its result and its cost would be lost.

#### Scenario: Request shape
- **WHEN** a research run is submitted at depth `high`
- **THEN** the request has preset `high`, `background` true and `store` true

### Requirement: Job records
Each started run SHALL be kept as a local job row in table `research_jobs` (migration `0004`) belonging to its project: query, depth, response id, last known status, resolved model, our own start and finish times, the result text and sources once finished, a usage summary, a flag saying whether usage was recorded, and when a cancel was requested. The provider's `created_at` and `completed_at` SHALL NOT be stored: the API overwrites both with the time of each fetch.

#### Scenario: Our own times
- **WHEN** a run is submitted and then fetched twice by `status`
- **THEN** the job's start time is the time of submission and does not change when the fetched snapshots carry different `created_at` values

#### Scenario: Migration up and down
- **WHEN** a revision-0003 database is upgraded to 0004, downgraded and upgraded again
- **THEN** the table is created with the backup for revision 0003, dropped on downgrade with `projects`, `chats` and `usage_events` intact, and created again

#### Scenario: Project deletion
- **WHEN** a project with 2 jobs is deleted with `confirm` true
- **THEN** the jobs are gone and counted in `rows_removed`, and usage events already recorded remain reportable by name

### Requirement: Submit is not a costed call yet
A submit that returns a queued or in-progress run SHALL create the job row and record no usage event. A submit that fails SHALL create no job row and record one failure event with its error category and no usage. The project SHALL be resolved and committed before the call and the job row written after it.

#### Scenario: Queued run records nothing
- **WHEN** a research submit returns the recorded queued response
- **THEN** no usage event exists for it

#### Scenario: Failed submit
- **WHEN** the API answers a submit with a 429 whose `Retry-After` exceeds the maximum wait
- **THEN** the tool fails with `rate_limited`, no job row exists and one event with status `rate_limited` and cost 0 exists

### Requirement: Jobs tool
The server SHALL provide `perplexity_jobs` with actions `list`, `status`, `result` and `cancel`, each scoped to a `project` (default `default`); `status`, `result` and `cancel` take a `job_id`. A job in another project, or an unknown one, SHALL fail with `not_found` before any upstream call. The tool SHALL return after at most the upstream calls the action needs and never wait for a run to progress.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_jobs` and `perplexity_research` are present with typed parameters and output schemas

#### Scenario: Unknown job
- **WHEN** a client asks for the status of job 999
- **THEN** the call fails with `not_found` and no request reaches the API

#### Scenario: Missing id
- **WHEN** a client calls `status` without `job_id`
- **THEN** the call fails with `invalid_request` naming `job_id`

### Requirement: Status polls once
`status` on a job that is not terminal SHALL fetch the run once, update the job's status and model, and return the job with its progress: how many search and fetch steps the run has shown so far. A job already terminal SHALL be returned from local storage without an upstream call. Any status the API reports that is not terminal, including one this server has never seen, SHALL be returned verbatim and treated as still running.

#### Scenario: Running job
- **WHEN** a job is fetched and the API returns the recorded in-progress snapshot with 3 search results and 3 fetched pages
- **THEN** the result's status is `in_progress`, progress shows 3 searches and 3 fetches, there is no answer, and no usage event exists

#### Scenario: Terminal job served locally
- **WHEN** `status` is called on a job already finished
- **THEN** no request reaches the API

#### Scenario: Unknown status
- **WHEN** the API reports status `paused` for a job
- **THEN** the job's status is stored and returned as `paused`, nothing is recorded and no error is raised

### Requirement: Terminal states are observed once
The first fetch that shows a terminal status (`completed`, `failed`, `incomplete` or `cancelled`) SHALL store the finish time, the model, the answer text and sources when present, the usage summary, and record usage; later calls on that job SHALL NOT fetch or record again.

#### Scenario: Completed run
- **WHEN** a job's fetch returns the recorded completed snapshot
- **THEN** the job is `completed` with the answer and sources stored, and exactly one usage event exists with tool `perplexity_research`, preset `medium`, the resolved model, the response id, status `ok` and cost 15990000 nano-USD, source `reported`

#### Scenario: Observed twice
- **WHEN** `status` and then `result` are called on the finished job
- **THEN** one usage event exists and only the first call reached the API

### Requirement: Unsuccessful terminal runs are recorded
A terminal run that is not `completed` SHALL be recorded once with status `unexpected_response` and whatever usage it reports. A cancelled run reports no usage, so its event has cost 0 and source `none`, which the usage report counts as unknown cost.

#### Scenario: Cancelled run
- **WHEN** a job's fetch returns the recorded cancelled snapshot
- **THEN** the job is `cancelled`, no answer is stored, and one event exists with status `unexpected_response`, cost 0 and source `none`

#### Scenario: Pending run never recorded
- **WHEN** a job's fetch returns a queued or in-progress snapshot
- **THEN** no usage event exists for it

### Requirement: Result action
`result` SHALL return the stored answer, sources and usage summary of a completed job. For a job that is not terminal it SHALL fetch once like `status` and return the state without an answer and a message saying the run is not finished. For a terminal job without an answer it SHALL say why (cancelled, failed or incomplete).

#### Scenario: Completed job
- **WHEN** `result` is called for the finished job
- **THEN** it returns the answer text, de-duplicated sources and the cost string `0.01599`

#### Scenario: Not finished
- **WHEN** `result` is called while the run is in progress
- **THEN** it returns status `in_progress`, no answer and a message to try again later

### Requirement: Cancel
`cancel` SHALL fetch the run first. A terminal run SHALL be reported as it is, with no cancel request. A running one SHALL be cancelled with one request and reported as `cancelling`; the job's status becomes `cancelled` when a later fetch shows it. A cancel rejected as already terminal SHALL trigger one more fetch and report that state, not an error. A run whose cancel was already requested and which still runs SHALL be reported `cancelling` without a second request.

#### Scenario: Running job cancelled
- **WHEN** the fetch shows `in_progress` and the cancel request returns the recorded `cancelling` response
- **THEN** the result has status `cancelling`, the job records that a cancel was requested and no usage event exists yet

#### Scenario: Finished before the cancel
- **WHEN** the fetch shows `in_progress` and the cancel request returns the recorded already-terminal 400, and the refetch shows `completed`
- **THEN** the result reports `completed`, no error is raised and the finished run is recorded once

#### Scenario: Cancel of a terminal job
- **WHEN** a job already finished is cancelled
- **THEN** its state is reported and no cancel request reaches the API

#### Scenario: Cancel twice
- **WHEN** a second cancel arrives for a job whose first cancel is still pending
- **THEN** the result is `cancelling` and no second cancel request is sent

### Requirement: Runs the provider no longer knows
When a fetch of a non-terminal job returns `not_found`, the job SHALL be marked `lost`, terminal locally, and returned with a warning that the run is unknown to the provider and its spend, if any, was not recorded. No usage event is created and no error is raised.

#### Scenario: Unknown run
- **WHEN** the API answers a job's fetch with the recorded 404 body
- **THEN** the job's status is `lost`, a warning is returned, no event exists and later calls do not fetch again

### Requirement: Listing jobs
`list` SHALL return the project's jobs newest first with id, depth, status, a query excerpt of at most 120 characters, start and finish times and whether usage was recorded, honoring `limit` (default 20, 1 to 100) and reporting the total and whether the list was cut. With `refresh` true it SHALL first fetch each non-terminal job of the project, at most 10 and oldest first, so finished runs are observed and recorded.

#### Scenario: Plain list
- **WHEN** a project has a finished and a running job
- **THEN** both are listed newest first and no request reaches the API

#### Scenario: Refresh settles finished runs
- **WHEN** `refresh` is true and the API reports the running job as completed
- **THEN** the job is listed as `completed` and one usage event exists

#### Scenario: Refresh is bounded
- **WHEN** 12 jobs are running and `refresh` is true
- **THEN** 10 fetches are made and the result says 2 were not refreshed

### Requirement: Recording follows the recorder contract
A usage event for a job SHALL be recorded while no write unit is open, before the job row's own update, with the job's project name, preset equal to its depth, and latency measured from the job's start to the observation. If the update fails after the event was recorded, a later call SHALL NOT record a second event for an `ok` run.

#### Scenario: Update fails after recording
- **WHEN** the job row's update fails after the event for a completed run was recorded, and the job is observed again
- **THEN** one event exists for that response id

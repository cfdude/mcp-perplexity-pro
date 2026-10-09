# agent-research Specification

## Purpose
Defines `perplexity_research` and `perplexity_jobs`: long research runs that execute in the background at the provider, the local job records that track them, and how their cost is recorded once the run reaches a terminal state, so that no tool call ever waits for a run to finish.

## Requirements

### Requirement: Research tool
The server SHALL provide `perplexity_research`, which starts a background run for one `query` (not blank, at most 20000 characters) and returns at once with a local `job_id`, the provider's `response_id`, the status the provider reported and the project. `depth` SHALL be `medium` (the default), `high` or `xhigh`; `instructions` (at most 10000 characters) and `project` are optional. It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` false and `openWorldHint` true.

#### Scenario: Submit
- **WHEN** a client starts research at the default depth and the API returns the recorded queued response
- **THEN** the result has a `job_id`, the response id, `status` `queued` and depth `medium`, and a job row with that id exists for the project

#### Scenario: Blank query
- **WHEN** a client starts research with a blank query
- **THEN** the call fails with `invalid_request`, no request reaches the API and no job or project is created

#### Scenario: Unknown depth
- **WHEN** a client passes depth `fast`
- **THEN** the call fails with `invalid_request` naming `perplexity_ask`

### Requirement: Research cost and retention are stated
The description of `perplexity_research` SHALL state that `medium` costs about $0.016 to $0.05, that `high` can cost up to about $0.4 to $0.9 and `xhigh` more (estimates, not measured by this server), that results are read with `perplexity_jobs`, and that research runs are stored by the provider (`store` true) so that the query and result stay retrievable there.

#### Scenario: Description
- **WHEN** a client lists the tools
- **THEN** the description of `perplexity_research` names the `medium` and `high` cost ranges and `perplexity_jobs`

#### Scenario: Retention wording
- **WHEN** a client lists the tools
- **THEN** the description of `perplexity_research` says the provider stores the run and does not claim that nothing is retained

### Requirement: Runs are background and retrievable
Every research request SHALL set `background` true and `store` true, and the tool SHALL offer no way to set `store` false: the API makes a background run with `store` false unretrievable, so its result and its cost would be lost.

#### Scenario: Request shape
- **WHEN** a research run is submitted at depth `high`
- **THEN** the request has preset `high`, `background` true and `store` true

### Requirement: Job records
Each started run SHALL be a row of `research_jobs` (migration `0004`, ids never reused) in its project: query, depth, response id, status, model, our own start and finish times, result text and sources, the usage summary (input, output and total tokens, cost, source), whether usage was recorded, when a cancel was requested and when the provider first did not know the run. The provider's `created_at` and `completed_at` SHALL NOT be stored: the API rewrites both on every fetch.

#### Scenario: Our own times
- **WHEN** a run is submitted and then fetched twice by `status`
- **THEN** the job's start time is the time of submission and does not change when the fetched snapshots carry different `created_at` values

#### Scenario: Migration up and down
- **WHEN** a revision-0003 database is upgraded to 0004, downgraded and upgraded again
- **THEN** the table is created with the backup named for revision 0003, dropped on downgrade with `projects`, `chats` and `usage_events` intact, and created again

#### Scenario: Live database upgrades straight to head
- **WHEN** a revision-0002 database holding rows is upgraded with the real migrations
- **THEN** it reaches revision 0004 in one run with exactly one backup, named for revision 0002, and no backup named for 0003

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

### Requirement: Submit that returns another status
A submit whose status is terminal (`completed`, `failed`, `incomplete`, `cancelled`, or any status with a non-null `error`) SHALL create the job row as terminal with its result, be recorded once by the submit itself, and be stored with `usage_recorded` set so no later observation records it again. Any other status SHALL be stored verbatim (redacted, cut to 64 characters), as a running job, with no event.

#### Scenario: Run finished at submit
- **WHEN** a submit returns the recorded completed snapshot
- **THEN** the job is `completed` with its answer stored, exactly one event exists, and a later `status` neither fetches nor records

#### Scenario: Unknown submit status
- **WHEN** a submit returns status `paused`
- **THEN** the job row is stored with status `paused`, no event exists and no error is raised

### Requirement: A started run is never orphaned silently
The response id the API returns SHALL match `resp_` followed by 1 to 100 letters, digits, hyphens or underscores before the job row is inserted, else the call fails with `unexpected_response`. When the insert of the row fails after a successful submit it SHALL be retried once; on a second failure the call SHALL fail with the mapped category, the message SHALL contain the response id so the run can be cancelled by hand, and the id SHALL be logged at ERROR.

#### Scenario: Row insert keeps failing
- **WHEN** the API accepts a submit and the job insert fails twice
- **THEN** the call fails, its message contains the response id, and an ERROR log record contains the id and no key

#### Scenario: Malformed response id
- **WHEN** the API returns a submit response whose id is `x/../y`
- **THEN** the call fails with `unexpected_response` and no job row exists

### Requirement: Upstream text in jobs is redacted and capped
Every string from the API that a job stores or a result returns (a status, an error text, a reason, a warning built from one) SHALL be redacted and capped as the ask tool's rule "Upstream text is redacted and capped" says. A stored query has the configured key replaced by `[redacted]`.

#### Scenario: Key-shaped status
- **WHEN** a fetch reports a status containing a `pplx-` shaped token
- **THEN** the stored and returned status has the token removed and is cut to 64 characters

### Requirement: Jobs tool
The server SHALL provide `perplexity_jobs` with actions `list`, `status`, `result` and `cancel`, scoped to a `project` (default `default`); the last three take a `job_id`. It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` true (a cancel is final) and `openWorldHint` true. An unknown job or one in another project SHALL fail with `not_found` before any upstream call. It SHALL never wait for a run to progress.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_jobs` and `perplexity_research` are present with typed parameters, output schemas and the annotations named for each

#### Scenario: Unknown job
- **WHEN** a client asks for the status of job 999
- **THEN** the call fails with `not_found` and no request reaches the API

#### Scenario: Missing id
- **WHEN** a client calls `status` without `job_id`
- **THEN** the call fails with `invalid_request` naming `job_id`

### Requirement: Jobs result vocabulary
The `perplexity_jobs` result SHALL carry a top-level `job_id` (the job the action concerns; null for `list`) and a top-level `status` (null for `list`) that is the state the action reports: `queued`, `in_progress`, `completed`, `failed`, `incomplete`, `cancelled`, `lost`, `cancelling`, or an unknown API status verbatim. `cancelling` SHALL be reported only by `cancel` and never stored. The `job` record and every `jobs[]` record SHALL carry their own `job_id` and their stored `status`.

#### Scenario: Ids and states in each action
- **WHEN** `status`, `result` and `cancel` are called for job 7, and `list` is called for its project
- **THEN** the first three results have `job_id` 7 and a top-level `status`, the `job` record has `job_id` 7, and the `list` result has null `job_id` and `status` with `job_id` 7 inside its `jobs[]` record

#### Scenario: Cancelling is not stored
- **WHEN** a cancel is accepted for a running job
- **THEN** the result's `status` is `cancelling` while the `job` record's stored `status` is still `in_progress`

### Requirement: Jobs actions never create a project
Every `perplexity_jobs` action SHALL look the project up and never create it. In an absent project `list` SHALL return no jobs with total 0, and `status`, `result` and `cancel` SHALL fail with `not_found`. A `job_id` that is not a positive integer below 2**63 SHALL fail with `invalid_request`, also in an absent project, while an unknown positive id SHALL fail with `not_found`.

#### Scenario: List in an absent project
- **WHEN** a client lists jobs of project `ghost`, which does not exist
- **THEN** the result has no jobs and total 0, and project `ghost` still does not exist

#### Scenario: Status in an absent project
- **WHEN** a client asks for the status of job 1 in project `ghost`
- **THEN** the call fails with `not_found`, no request reaches the API and `ghost` still does not exist

#### Scenario: An id the database cannot hold
- **WHEN** a client asks for the status of job 0, of job -1, and of job 9223372036854775808 (2**63), the last naming the absent project `ghost`
- **THEN** each call fails with `invalid_request` naming `job_id`, no request reaches the API and `ghost` still does not exist, while job 999 of an existing project fails with `not_found`

### Requirement: Status polls once
`status` on a job that is not terminal SHALL fetch the run once, update the job's status, and return the job with its progress: how many search and fetch steps the run has shown so far. A job already terminal SHALL be returned from local storage without an upstream call. Any status the API reports that is not terminal, including one this server has never seen, SHALL be returned verbatim (redacted, cut to 64 characters) and treated as still running.

#### Scenario: Running job
- **WHEN** a job is fetched and the API returns the recorded in-progress snapshot with 3 search results and 3 fetched pages
- **THEN** the result's `status` is `in_progress`, progress shows 3 searches and 3 fetches, there is no answer, and no usage event exists

#### Scenario: Terminal job served locally
- **WHEN** `status` is called on a job already finished
- **THEN** no request reaches the API

#### Scenario: Unknown status
- **WHEN** the API reports status `paused` for a job
- **THEN** the job's status is stored and returned as `paused`, nothing is recorded and no error is raised

### Requirement: The model is known only from a finished run
A snapshot's `model` SHALL be stored and recorded only when the snapshot is `completed`, or when its value contains `/` and differs from the job's depth. The API reports the preset name (such as `medium`) as `model` on queued, in-progress and cancelled snapshots, and that is not a model.

#### Scenario: Preset name is not a model
- **WHEN** a queued or in-progress snapshot reports model `medium` for a job of depth `medium`
- **THEN** the job's model stays empty

#### Scenario: Completed snapshot
- **WHEN** the recorded completed snapshot reports `openai/gpt-6-luna`
- **THEN** the job's model and the recorded event's model are `openai/gpt-6-luna`

### Requirement: Terminal states are observed once
The first fetch that shows a terminal status (`completed`, `failed`, `incomplete`, `cancelled`, or any status with a non-null `error`) SHALL store the finish time, the model when known, the answer text and sources when present, the usage summary, and record usage; later calls on that job SHALL NOT fetch or record again. A snapshot with an error and a status other than `failed`, `incomplete` or `cancelled` is stored as `failed`.

#### Scenario: Completed run
- **WHEN** a job's fetch returns the recorded completed snapshot
- **THEN** the job is `completed` with the answer and sources stored, and exactly one usage event exists with tool `perplexity_research`, preset `medium`, the resolved model, the response id, status `ok` and cost 15990000 nano-USD, source `reported`

#### Scenario: Observed twice
- **WHEN** `status` and then `result` are called on the finished job
- **THEN** one usage event exists and only the first call reached the API

#### Scenario: Error with an odd status
- **WHEN** a fetch returns status `paused` with a non-null `error`
- **THEN** the job is stored as `failed`, one event with status `unexpected_response` exists and no later call fetches

### Requirement: Overlapping observations record once
The observation of one job SHALL be serialized by an in-process lock per job, and the terminal test SHALL be repeated after the lock is taken from the stored row, so overlapping `status`, `list` refresh and `cancel` calls produce one event whatever the terminal status. (The database's duplicate guard covers `ok` events only.)

#### Scenario: Concurrent observation
- **WHEN** two `status` calls on the same running job overlap and its fetch shows the recorded cancelled snapshot
- **THEN** exactly one usage event exists for that response id and the second call returns the stored result without a second fetch

### Requirement: Unsuccessful terminal runs are recorded
A terminal run that is not `completed` (`failed`, `incomplete`, `cancelled` or one with an error) SHALL be recorded once with status `unexpected_response` and whatever usage it reports. A cancelled run reports no usage, so its event has cost 0, source `none` and no model, which `perplexity_usage` counts as an error and as unknown cost (`calls_cost_unknown`).

#### Scenario: Cancelled run
- **WHEN** a job's fetch returns the recorded cancelled snapshot
- **THEN** the job's stored status is `cancelled`, no answer is stored, and one event exists with status `unexpected_response`, no model, cost 0 and source `none`

#### Scenario: Failed or incomplete run
- **WHEN** a job's fetch returns a `failed` or an `incomplete` snapshot
- **THEN** one event exists with status `unexpected_response` and the usage the snapshot reported

#### Scenario: Pending run never recorded
- **WHEN** a job's fetch returns a queued or in-progress snapshot
- **THEN** no usage event exists for it

### Requirement: Observations commit per job
An observation of a job SHALL be its usage event (the recorder's own unit) and then its row update (its own unit); no two jobs share a unit. A call observing runs (`refresh`, or a cancel's fetch and refetch) SHALL commit each observation in its own unit and a cancel's `cancel_requested_at` write in another; a failure rolls back only its own unit. In `refresh` a failed observation SHALL be a warning naming the job id and category, the list is still returned and the job counts in `not_refreshed`.

#### Scenario: Refresh with one failing fetch
- **WHEN** `refresh` observes three running jobs and the second job's fetch fails with `upstream_failure`
- **THEN** the first and third jobs are observed and committed, a warning names the second job's id and `upstream_failure`, and `not_refreshed` is 1

### Requirement: Result action
`result` SHALL return the stored answer, sources and the same usage summary as the ask tool for a completed job. For a job that is not terminal it SHALL fetch once like `status` and return the state without an answer and a message saying the run is not finished. For a terminal job without an answer it SHALL say why (cancelled, failed, incomplete or lost).

#### Scenario: Completed job
- **WHEN** `result` is called for the finished job
- **THEN** it returns the answer text, de-duplicated sources, the cost string `0.01599` and input, output and total tokens from the stored columns

#### Scenario: Not finished
- **WHEN** `result` is called while the run is in progress
- **THEN** it returns `status` `in_progress`, no answer and a message to try again later

### Requirement: Cancel
`cancel` SHALL fetch the run first, even when a cancel is already pending. A terminal run SHALL be reported as it is, with no cancel request. A running one SHALL be cancelled with one request and reported as `cancelling`; the job's status becomes `cancelled` when a later fetch shows it. A cancel rejected as already terminal SHALL trigger one more fetch and report that state, not an error. A run whose cancel is pending and still runs SHALL be reported `cancelling` without a second request.

#### Scenario: Running job cancelled
- **WHEN** the fetch shows `in_progress` and the cancel request returns the recorded `cancelling` response
- **THEN** the result's `status` is `cancelling`, the job records that a cancel was requested and no usage event exists yet

#### Scenario: Finished before the cancel
- **WHEN** the fetch shows `in_progress` and the cancel request returns the recorded already-terminal 400, and the refetch shows `completed`
- **THEN** the result's `status` is `completed`, no error is raised and the finished run is recorded once

#### Scenario: Cancel of a terminal job
- **WHEN** a job already finished is cancelled
- **THEN** its state is reported and no cancel request reaches the API

#### Scenario: Cancel twice
- **WHEN** a second cancel arrives for a job whose first cancel is still pending and the fetch still shows it running
- **THEN** the run is fetched again, the result's `status` is `cancelling` and no second cancel request is sent

#### Scenario: Pending cancel finished meanwhile
- **WHEN** a second cancel arrives and its fetch shows the recorded cancelled snapshot
- **THEN** the result's `status` is `cancelled`, one event is recorded and no cancel request is sent

### Requirement: A cancel that was accepted is not lost to a local failure
When the local write that records `cancel_requested_at` fails after the API accepted the cancel, the result SHALL still be returned with a warning `not_saved` instead of an error, since the run is being cancelled whatever the row says.

#### Scenario: Write fails after an accepted cancel
- **WHEN** the cancel request is accepted and the row update fails with a busy database
- **THEN** the result's `status` is `cancelling` with a `not_saved` warning

### Requirement: Runs the provider no longer knows
A `not_found` fetch of a non-terminal job SHALL record the time (`missing_since`), return the job as still running with a warning, and send no cancel request. The job SHALL become `lost`, terminal locally, only when a further fetch is `not_found` and the run was submitted at least 10 minutes earlier (a chosen margin for propagation delay, not measured); a successful fetch clears the record. A `lost` job creates no event and raises no error.

#### Scenario: First not found
- **WHEN** the API answers a running job's fetch with the recorded 404 body for the first time
- **THEN** the job stays running with a warning, no event exists and no error is raised

#### Scenario: Confirmed lost
- **WHEN** a job submitted 11 minutes ago whose first 404 was recorded gets another 404
- **THEN** the result's `status` and the job's stored status are `lost`, a warning says its spend was not recorded, no event exists and later calls do not fetch

#### Scenario: Not found twice but too early
- **WHEN** a job submitted 2 minutes ago gets a second 404
- **THEN** the job stays running with a warning

### Requirement: Listing jobs
`list` SHALL return the project's jobs newest first with id, depth, status, a query excerpt of at most 120 characters, start and finish times and whether usage was recorded, honoring `limit` (default 20, 1 to 100) and reporting the total and whether the list was cut. With `refresh` true it SHALL first observe the project's non-terminal jobs ordered by `last_checked_at` ascending (never checked first, ties by job id), at most 10, so finished runs are recorded.

#### Scenario: Plain list
- **WHEN** a project has a finished and a running job
- **THEN** both are listed newest first and no request reaches the API

#### Scenario: Refresh settles finished runs
- **WHEN** `refresh` is true and the API reports the running job as completed
- **THEN** the job is listed as `completed` and one usage event exists

#### Scenario: Refresh is bounded and fair
- **WHEN** 12 running jobs exist, two of them never checked, and `refresh` is true
- **THEN** 10 fetches are made, starting with the two never checked, and the result says 2 were not refreshed

### Requirement: Deleting a project reports its running jobs
`perplexity_projects` `delete` SHALL count the project's non-terminal jobs and report them as `running_jobs`, with a warning that their spend will never be recorded and the provider keeps billing them until they end, and that `perplexity_jobs` `cancel` should come first. Without `confirm` the `confirmation_required` error SHALL carry the same warning.

#### Scenario: Delete with running jobs
- **WHEN** a project with one running and one finished job is deleted with `confirm` true
- **THEN** the result has `running_jobs` 1 and a warning naming it, and both jobs are gone

#### Scenario: Unconfirmed delete
- **WHEN** the same project is deleted without `confirm`
- **THEN** the call fails with `confirmation_required` and its message carries the running-jobs warning

### Requirement: Recording follows the recorder contract
A usage event for a job SHALL be recorded while no write unit is open, before the job row's own update, with the job's project name, preset equal to its depth, and latency measured from the job's start to the observation. If the update fails after the event was recorded, a later call SHALL NOT record a second event for a run of any terminal status: it finds the event and writes only the row.

#### Scenario: Update fails after recording
- **WHEN** the job row's update fails after the event for a completed run was recorded, and the job is observed again
- **THEN** one event exists for that response id

#### Scenario: Cancelled run whose update failed
- **WHEN** the row update of a cancelled run fails once after its event was recorded, and the job is observed again
- **THEN** still one event exists for that response id and the second observation writes the row as `cancelled`

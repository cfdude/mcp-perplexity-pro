# model-matrix Specification

## Purpose
Defines the on-disk matrix of models, prices and accepted effort levels that the server keeps current by itself, so routing can rely on facts learned from the API instead of values written by hand.

## Requirements

### Requirement: The matrix is one versioned file in the data directory
The server SHALL keep `model_matrix.json` in `PERPLEXITY_DATA_DIR`, created with mode 0600, holding `version` 1, `fetched_at` and one entry per model id.

#### Scenario: Top level
- **WHEN** the file is read
- **THEN** it has `version` 1, a UTC `fetched_at` and a `models` mapping keyed by model id

#### Scenario: A refreshed file
- **WHEN** the server has refreshed against the live list
- **THEN** the file parses, has `version` 1 and an entry for every listed model with its price, and its mode is 0600

### Requirement: Each model entry holds prices and availability
An entry SHALL hold the model's provider, its pricing (input, output, cache read and cache write per million tokens, or null), `status` (`available` or `removed`), `first_seen`, `last_seen`, `probing_until` (a UTC time or null) and its `efforts`.

#### Scenario: An entry
- **WHEN** a listed model is merged
- **THEN** its entry holds the provider, the four prices or null, `status` `available`, `first_seen`, `last_seen` and `probing_until` null

### Requirement: Efforts have one shape
A model's `efforts` SHALL hold `accepted` (a list of levels), `refused` (a level mapped to its HTTP status), `answers` (the control and each answered level mapped to its HTTP status, kept while a probe is incomplete), `probed_at` and `source` (`probe`, `baseline` or `unprobed`). A level is one effort value; `efforts` is the per-model facts.

#### Scenario: Efforts shape
- **WHEN** a model's efforts were probed and it refused two levels
- **THEN** its `efforts` hold `accepted` as a list of levels, `refused` as `{"xhigh": 400, "max": 400}`, `probed_at` as a UTC time and `source` `probe`

### Requirement: The matrix is never empty
A baseline matrix SHALL ship inside the package with every model known when it was built and its probed efforts. When the file is missing, unreadable, empty or has a `version` the code does not know, the server SHALL use the baseline in memory; an unreadable or empty file SHALL be renamed aside with a `.corrupt-` suffix before any write, and a newer-version file SHALL be left untouched.

#### Scenario: First start
- **WHEN** the server starts with no `model_matrix.json`
- **THEN** the matrix in memory equals the baseline and every baseline model has its efforts

#### Scenario: A corrupt file
- **WHEN** the file holds text that is not JSON
- **THEN** the baseline is used, the file is renamed with a `.corrupt-` suffix and the server starts

#### Scenario: A file from a newer version
- **WHEN** the file has `version` 2
- **THEN** the baseline is used in memory and the file is not modified

### Requirement: Reading the matrix is lazy and never writes
The in-memory matrix SHALL be loaded from the file (else the baseline) on first use, by `perplexity_models` or the refresh task, and never at server construction; only the refresh task writes the file, so a one-shot command that reads the matrix writes nothing and `perplexity-pro help` and the schema builder touch no data directory.

#### Scenario: A one-shot read
- **WHEN** `perplexity-pro models` runs against a data directory holding a matrix file
- **THEN** its efforts come from that file, with origin `file`, and the file is not modified

#### Scenario: Help touches nothing
- **WHEN** `perplexity-pro help` runs
- **THEN** no data directory is created or read

### Requirement: A refresh task runs in a serving process
In a serving process (`mcp-perplexity-pro` over either transport and `perplexity-pro serve`) a background task started with the server SHALL fetch the live model list afresh (not from the catalog cache) at start and then every `PERPLEXITY_MATRIX_REFRESH` seconds (0 meaning only at start), merge it into the matrix and write the file. A one-shot command, the schema builder and the test servers SHALL start no task.

#### Scenario: Periodic refresh
- **WHEN** `PERPLEXITY_MATRIX_REFRESH` elapses (the test patches the interval)
- **THEN** the list is fetched again, bypassing the catalog cache, and the file is rewritten with a new `fetched_at`

#### Scenario: A one-shot command
- **WHEN** `perplexity-pro usage` or the schema builder runs
- **THEN** no request is made to the models endpoint and no matrix file is written

### Requirement: A refresh never blocks or fails the server
Startup SHALL NOT wait for the refresh, and any failure of it SHALL log one warning (no secret) and leave the matrix as it was.

#### Scenario: Startup does not wait
- **WHEN** the models endpoint is held open by the test and a tool call is made
- **THEN** the call completes while the endpoint is still held, and the matrix is the baseline or the stored file until it is released

#### Scenario: The list cannot be fetched
- **WHEN** the models endpoint answers 500, even with a fresh list cached
- **THEN** one warning is logged, the file is unchanged and the server keeps serving

### Requirement: Merging keeps what is known
A merge SHALL add an id not in the matrix as `available` with the baseline's efforts when the baseline knows it, else `unprobed`; update the price and `last_seen` of a listed id; mark a stored id absent from the list `removed` while keeping its row and efforts; mark a reappearing `removed` id `available`; and change nothing, with a warning, when the list is empty or holds fewer than half of the stored `available` ids. A `removed` model is not listed, probed or counted as unprobed.

#### Scenario: A new model
- **WHEN** the live list holds an id the matrix lacks
- **THEN** it is added `available` with efforts source `unprobed` and its price

#### Scenario: A vanished model
- **WHEN** a stored id is missing from a list of 50 models
- **THEN** it is `removed`, its row and efforts are kept

#### Scenario: An empty list
- **WHEN** the endpoint answers an empty list
- **THEN** no model is marked `removed`

#### Scenario: A truncated list
- **WHEN** the endpoint answers 10 of 54 stored ids
- **THEN** nothing changes and one warning is logged

#### Scenario: A model the baseline knows
- **WHEN** a live id is missing from the stored file but present in the baseline
- **THEN** it is added with the baseline's efforts, source `baseline`, and is not probed

### Requirement: Writes are atomic and safe between servers
The file SHALL be written to a temporary file and replaced in one step, under an exclusive lock file `model_matrix.lock`, re-reading and merging the stored file inside the lock so that two servers sharing the directory do not lose each other's rows.

#### Scenario: Two writers
- **WHEN** one writer holds the lock and a second writes a different new model after it releases
- **THEN** the final file holds both, and the second never wrote from a stale read

### Requirement: The lock is short and cancellable
The lock wait SHALL be bounded at 5 seconds and end at once when the task is cancelled (the lock is polled without a thread, so a cancelled wait never takes or holds the lock), the lock SHALL never be held across a network request, a lock that cannot be taken SHALL skip that write with one warning, and temporary files left by a killed writer SHALL be removed by the next writer.

#### Scenario: A lock that cannot be taken
- **WHEN** another process holds the lock for longer than 5 seconds
- **THEN** the write is skipped, one warning is logged and the file is unchanged

#### Scenario: A cancelled wait
- **WHEN** the task is cancelled while waiting for the lock
- **THEN** the wait ends at once and no write happens

#### Scenario: A cancelled write
- **WHEN** the task is cancelled during a write
- **THEN** the file on disk is either the old complete file or the new complete file

### Requirement: New models are probed for accepted efforts
For each `available` model whose efforts are `unprobed`, at most ten per refresh and only when `PERPLEXITY_MATRIX_PROBE` is `new`, the task SHALL send one control request with no effort and one request per level (`minimal`, `low`, `medium`, `high`, `xhigh`, `max`), each with a fixed tiny prompt, no tools and a 30-second limit. A completed 200 means accepted; a 400 means refused, recorded with its status, but only when the control request completed. 

#### Scenario: A model that refuses xhigh
- **WHEN** a new model completes the control and the first four levels and answers 400 to `xhigh` and `max`
- **THEN** its efforts list the four accepted and `xhigh` and `max` refused with 400, source `probe`

#### Scenario: A model that refuses everything
- **WHEN** the control completes and all six levels answer 400
- **THEN** every level is recorded refused, source `probe`

#### Scenario: A broken control
- **WHEN** the control request does not complete (a 400, a 5xx, a failed run)
- **THEN** no level result is recorded as refused and the model stays `unprobed`

#### Scenario: Probing off
- **WHEN** `PERPLEXITY_MATRIX_PROBE` is `off`
- **THEN** no probe request is made and new models stay `unprobed`

### Requirement: Paid answers are written per model and survive a cancel
Answers SHALL be written to the file after each model's requests, including a model cut short by a cancel, a cap or a 429, shielded from cancellation and bounded by the lock wait, so answers already paid for survive a shutdown.

#### Scenario: Paid answers survive a shutdown
- **WHEN** the task is cancelled after three levels of a model were answered
- **THEN** the file holds those three answers in `answers` and the next refresh sends only the other levels

### Requirement: A probe result needs every level answered
A model's efforts SHALL be marked source `probe` with `probed_at`, and `accepted` and `refused` filled, only when the control and all six levels were answered as above. Answers already received SHALL be kept in `answers`, and only unanswered levels are sent again at the next refresh. A 429 SHALL end that refresh's probing; a 5xx, a timeout or a run that did not complete leaves that level unanswered.

#### Scenario: A rate-limited level
- **WHEN** one level answers 429
- **THEN** probing stops for that refresh, the answered levels are kept and only the rest are sent next time

#### Scenario: A run that did not complete
- **WHEN** a 200 body reports status `failed` or `incomplete`
- **THEN** that level is unanswered, neither accepted nor refused

### Requirement: A probe is bounded, recorded and not duplicated
Each probe request SHALL be one attempt with no retry, and every one that returns a response or fails with an error SHALL be recorded as a usage event. A refresh SHALL stop probing after ten models or when the reported cost so far reaches $0.25, checked before each model. Before probing a model, a task SHALL write a 10-minute `probing_until` lease on it under the lock and clear it afterwards, and SHALL skip any model whose lease is unexpired or already probed.

#### Scenario: Ten at most
- **WHEN** a refresh finds 14 unprobed models
- **THEN** 10 are probed (70 requests) and the other 4 wait for the next refresh

#### Scenario: The spend cap
- **WHEN** the reported cost of one refresh's probes reaches $0.25
- **THEN** no further model is started and the remaining models wait

#### Scenario: A lease is cleared
- **WHEN** a model's probe ends, completes or is cut short
- **THEN** its `probing_until` is null

#### Scenario: Leased by another server
- **WHEN** another server holds an unexpired lease on a model
- **THEN** this server does not probe it

#### Scenario: Already probed elsewhere
- **WHEN** another server wrote a complete probe result for a model after this server read the file
- **THEN** this server re-reads under the lock and does not probe it

### Requirement: Shutdown stops the task
On shutdown, in both transports and on stdin EOF, the refresh task SHALL be cancelled and awaited before the HTTP client is closed, adding no wait of its own, and without corrupting the file.

#### Scenario: Shutdown during a probe over HTTP
- **WHEN** the server receives SIGTERM during a probe
- **THEN** the task is cancelled before the client closes, the process still exits within its bound and the matrix file is intact

#### Scenario: Shutdown over stdio
- **WHEN** a stdio server's input closes during a probe
- **THEN** the same holds

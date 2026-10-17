# Spec Delta

## Purpose
Defines the on-disk matrix of models, prices and accepted effort levels that the server keeps current by itself, so routing can rely on facts learned from the API instead of values written by hand.

## ADDED Requirements

### Requirement: The matrix is one versioned file in the data directory
The server SHALL keep `model_matrix.json` in `PERPLEXITY_DATA_DIR`, created with mode 0600, holding `version` 1, `fetched_at`, `source` and one entry per model id with its provider, its pricing (input, output, cache read and cache write per million tokens, or null), `status` (`available` or `removed`), `first_seen`, `last_seen` and its `efforts`: the accepted levels, the refused levels with the HTTP status, `probed_at` and `source` (`probe`, `baseline` or `unprobed`).

#### Scenario: A refreshed file
- **WHEN** the server has refreshed against the live list
- **THEN** the file parses, has `version` 1 and an entry for every listed model with its price, and its mode is 0600

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

### Requirement: A refresh starts with the server and never blocks or fails it
A background task SHALL fetch the live model list at start and then every `PERPLEXITY_MATRIX_REFRESH` seconds (0 meaning only at start), merge it into the matrix and write the file. The server SHALL accept calls without waiting for it, and any failure of the task SHALL log one warning (no secret) and leave the matrix as it was.

#### Scenario: Startup does not wait
- **WHEN** the models endpoint takes 30 seconds to answer
- **THEN** the server accepts tool calls at once and the matrix is the baseline or the stored file until the answer arrives

#### Scenario: The list cannot be fetched
- **WHEN** the models endpoint answers 500
- **THEN** one warning is logged, the file is unchanged and the server keeps serving

#### Scenario: Periodic refresh
- **WHEN** `PERPLEXITY_MATRIX_REFRESH` is 3600 and an hour has passed
- **THEN** the list is fetched again and the file is updated if anything changed

### Requirement: Merging keeps what is known
A merge SHALL add an id not in the matrix as `available` with efforts `unprobed`; update the price and `last_seen` of a listed id; mark a stored id absent from a non-empty list `removed` while keeping its row and efforts; mark a reappearing `removed` id `available`; and change nothing when the list is empty or unreadable.

#### Scenario: A new model
- **WHEN** the live list holds an id the matrix lacks
- **THEN** it is added `available` with efforts source `unprobed` and its price

#### Scenario: A vanished model
- **WHEN** a stored id is missing from a list of 50 models
- **THEN** it is `removed`, its row and efforts are kept

#### Scenario: An empty list
- **WHEN** the endpoint answers an empty list
- **THEN** no model is marked `removed`

### Requirement: Writes are atomic and safe between servers
The file SHALL be written to a temporary file and replaced in one step, under an exclusive lock file `model_matrix.lock` with a bounded wait of 10 seconds, re-reading and merging the stored file inside the lock so that two servers sharing the directory do not lose each other's rows. A lock that cannot be taken SHALL skip that write with one warning.

#### Scenario: Two writers
- **WHEN** two refreshes write different new models at nearly the same time
- **THEN** the final file holds both

#### Scenario: A cancelled write
- **WHEN** the task is cancelled during a write
- **THEN** the file on disk is either the old complete file or the new complete file

### Requirement: New models are probed for accepted efforts
For each `available` model whose efforts are `unprobed`, at most ten per refresh and only when `PERPLEXITY_MATRIX_PROBE` is `new`, the task SHALL send one request per level (`minimal`, `low`, `medium`, `high`, `xhigh`, `max`) with a fixed tiny prompt and no tools. A 200 means accepted and a 400 means refused, recorded with its status.

#### Scenario: A model that refuses xhigh
- **WHEN** a new model answers 200 to the first four levels and 400 to `xhigh` and `max`
- **THEN** its efforts list the four accepted and `xhigh` and `max` refused with 400, source `probe`

#### Scenario: Probing off
- **WHEN** `PERPLEXITY_MATRIX_PROBE` is `off`
- **THEN** no probe request is made and new models stay `unprobed`

### Requirement: A probe result needs all six answers
A model's efforts SHALL be marked source `probe` with `probed_at` only when all six levels were answered 200 or 400. A level answered otherwise (429, a 5xx, a timeout) SHALL leave the model `unprobed`, so the next refresh tries it again, and SHALL record nothing partial.

#### Scenario: A rate-limited level
- **WHEN** one level answers 429
- **THEN** the model stays `unprobed` and is tried again at the next refresh

### Requirement: A probe is bounded and recorded
Each probe request SHALL be one attempt with no retry, SHALL be recorded as a usage event, and a refresh SHALL stop probing after ten models. The probe SHALL not run for a model already probed, including one probed by another server on the shared file.

#### Scenario: Ten at most
- **WHEN** a refresh finds 14 unprobed models
- **THEN** 10 are probed (60 requests) and the other 4 wait for the next refresh

#### Scenario: Already probed elsewhere
- **WHEN** another server wrote a probe result for a model after this server read the file
- **THEN** this server re-reads inside the lock and does not probe it again

### Requirement: Shutdown stops the task
On shutdown the refresh task SHALL be cancelled and awaited within the server's shutdown bound, without corrupting the file.

#### Scenario: Shutdown during a probe
- **WHEN** the server receives SIGTERM during a probe
- **THEN** it exits within the bound and the matrix file is intact

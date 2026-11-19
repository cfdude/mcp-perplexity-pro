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
An entry SHALL hold the model's provider, its pricing (input, output, cache read and cache write per million tokens, or null), `status` (`available` or `removed`), `first_seen`, `last_seen`, `probing_until` (a UTC time or null), its `efforts` and its `inputs`.

#### Scenario: An entry
- **WHEN** a listed model is merged
- **THEN** its entry holds the provider, the four prices or null, `status` `available`, `first_seen`, `last_seen` and `probing_until` null

#### Scenario: An entry's inputs
- **WHEN** a listed model is merged and the baseline holds no row for it
- **THEN** its entry holds `inputs` with nothing accepted or refused

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
A merge SHALL add an id not in the matrix as `available` with the baseline's efforts and inputs when the baseline knows it, else `unprobed` and with nothing known for inputs; for each kind that is NOT `attempted` in an existing entry and answered by the baseline, copy that kind's answer only (never the bookkeeping of any other kind); update the price and `last_seen` of a listed id; mark a stored id absent from the list `removed` while keeping its row, efforts and inputs; mark a reappearing `removed` id `available`; and change nothing, with a warning, when the list is empty or holds fewer than half of the stored `available` ids. A `removed` model is not listed, probed or counted as unprobed.

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
- **THEN** it is added with the baseline's efforts and inputs, source `baseline`, and is not probed for any kind the baseline answers

#### Scenario: An upgraded entry takes the baseline's inputs
- **WHEN** a stored entry from before this change has no inputs known and the baseline holds its id
- **THEN** the merge copies the baseline's answer for each kind the baseline answers, source `baseline`, so the refresh does not probe 54 models

#### Scenario: A baseline-unknown model keeps its backoff
- **WHEN** a model the baseline leaves unknown for `document` has a `retry_after` 7 days ahead and a refresh merges the live list
- **THEN** the merge leaves that kind's `retry_after`, `unanswered_rounds` and `probed_at` unchanged

#### Scenario: An entry with its own answers
- **WHEN** a stored entry already knows a kind
- **THEN** the merge keeps its answer and fills only the kinds that are not attempted

#### Scenario: An attempted kind is not overwritten
- **WHEN** a stored entry has `unanswered_rounds` 1 and `attempts` 1 for `document` and the baseline answers `document` as accepted
- **THEN** the merge leaves `document` unknown with its counters unchanged

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
For each `available` model whose efforts are `unprobed`, at most ten per refresh and only when `PERPLEXITY_MATRIX_PROBE` is `new`, the task SHALL send one control request with no effort and one request per level (`minimal`, `low`, `medium`, `high`, `xhigh`, `max`), each with a fixed tiny prompt, no tools and a 30-second limit. A completed 200 means accepted; a 400 means refused, recorded with its status, but only when the control request completed. A model whose efforts are known but whose inputs need probing is selected by `Eligibility for an input probe is per kind` and sends no effort level.

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

#### Scenario: Known efforts, unknown inputs
- **WHEN** a model's efforts come from the baseline and its inputs are unanswered
- **THEN** the refresh sends it no effort level, only the input probe

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
Each probe request SHALL be one attempt with no retry, and every one that returns a response or fails with an error SHALL be recorded as a usage event. A refresh SHALL stop starting models after ten models, or once the recorded cost so far (a lower bound: an event with unknown cost counts as zero) is at or above $0.25, checked before each model; a model already started finishes its own requests, so a round can exceed $0.25 by one model's worst case. Before probing a model, a task SHALL write a 10-minute `probing_until` lease on it under the lock and clear it afterwards, and SHALL skip any model whose lease is unexpired or already probed.

#### Scenario: Ten at most
- **WHEN** a refresh finds 14 models that need probing
- **THEN** 10 are probed (at most 100 requests: 7 effort and 3 input requests each) and the other 4 wait for the next refresh

#### Scenario: The spend cap
- **WHEN** the reported cost of one refresh's probes, effort and input requests together, reaches $0.25
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

### Requirement: This capability owns the modality data
The model matrix is the only owner of which input kinds a model accepts. Kinds are `image` and `document` only (text is implicit; audio and video are refused before any route is resolved). Every other part of the server SHALL read modalities through `accepts`, `models_accepting` and `preset_accepts` and SHALL NOT keep its own modality table.

#### Scenario: One source
- **WHEN** `rg "input_modalities|modalit" src/ data/` is run after the change
- **THEN** every match is in `matrix.py`, the baseline, `perplexity_models` output text or a comment

### Requirement: The words unknown, unprobed, unanswered and refusal
The words `unprobed`, `unknown`, `unanswered` and `refusal` SHALL be used in the senses of the scenario below and not mixed.

#### Scenario: The vocabulary
- **WHEN** the matrix and its probes are described
- **THEN** `unprobed` is a `source` label (nothing has asked the model yet); `unknown` is what `accepts` answers for a kind neither accepted nor refused, or whose refusal has expired at the gate; `unanswered` is a probe request with no usable answer (a 5xx, a timeout, a failed run, a generic 400; a 429 is unanswered with no round counted and counts only in `attempts`); and `refusal` is one of three things, the API's named 400 (`is_named_refusal`), the recorded fact `refused`, or a run that `failed` with an error whose code or type is `refusal` (unanswered, never a `refused` fact)

### Requirement: Each model entry records the inputs it accepts
A model's `inputs` SHALL hold `accepted` (a list drawn from `image` and `document`), `refused` (a kind mapped to the HTTP status that refused it), `answers` (the round's control and each answered kind mapped to its status, kept while a probe is incomplete), `source` (`probe`, `baseline` or `unprobed`) and, PER KIND (objects keyed by `image` and `document`), `probed_at`, `last_attempt_at`, `attempts`, `unanswered_rounds` and `retry_after`.

#### Scenario: Inputs shape
- **WHEN** a model was probed and refused documents with 400
- **THEN** its `inputs` hold `accepted` `["image"]`, `refused` `{"document": 400}`, `probed_at` for each answered kind and source `probe`

### Requirement: One predicate says a kind was attempted
`attempts` SHALL count the requests sent for a kind and never reset; `unanswered_rounds` is the backoff counter and may reset. A kind is `attempted` when it has an answer (it is in `accepted` or `refused`), or its `retry_after` is not null, or its `attempts` is above 0, and the merge, `accepts` and the probe selector SHALL all use this one predicate.

#### Scenario: Attempted after a reset
- **WHEN** a kind was unanswered twice, its backoff counter was reset and its `retry_after` is set
- **THEN** it is `attempted`

#### Scenario: A baseline fill is not an attempt
- **WHEN** the merge copies the baseline's answer for a kind
- **THEN** the kind's `attempts` stays 0

### Requirement: A kind is known by its lists, not its source
A kind SHALL be known when it is in `accepted` or `refused`. `source` is only a label of where the newest answer came from, and no function SHALL read it to decide.

#### Scenario: A baseline answer is known
- **WHEN** a kind is in `accepted` with source `baseline`
- **THEN** `accepts` answers `yes` for it and no probe is selected for it

### Requirement: The matrix file stays version 1
The matrix file version SHALL stay 1. An entry with no `inputs` SHALL read as nothing known, and loading such a file SHALL NOT rewrite it. A server of an older release sharing the data directory ignores `inputs` and drops it from the file on its next write (the entry model ignores unknown keys); the newer server then re-probes, at a cost of at most about $0.02 per model, and this limit is stated in the README rather than guarded by a version bump.

#### Scenario: An entry from before this change
- **WHEN** a `model_matrix.json` written before this change is loaded
- **THEN** it loads without error, every kind is unknown, and the file is not rewritten by the load

#### Scenario: Version unchanged
- **WHEN** the file is written by this version
- **THEN** its top-level `version` is still 1

### Requirement: The packaged baseline records the 2026-10-30 sweep
The baseline SHALL give each of the 54 swept models an `inputs` record from the live sweep of 2026-10-30 (one image and one document request per model, `store` false), every answered kind carrying source `baseline` and `probed_at` `2026-10-30T00:00:00Z`. An entry added later (for example the hand-added `openai/gpt-6.1-terra`) carries unanswered inputs and no sweep date; the one dated exception is `xai/grok-4.7` (2026-11-11).

#### Scenario: Every model has inputs
- **WHEN** the baseline is loaded
- **THEN** all 54 swept entries hold an `inputs` record from the sweep, and any entry added later holds `inputs` with nothing answered

#### Scenario: The sweep counts
- **WHEN** the baseline is loaded
- **THEN** among the 54 swept models images are accepted for 48, refused for 0 and unknown for 6, and documents are accepted for 45, refused for 3 and unknown for 6 (the sweep's generic `invalid request` 400s are unknown, and `xai/grok-4.7` carries the dated 2026-11-11 re-probe); the count tests filter to the swept ids, so later additions do not move them

### Requirement: The baseline's answer rules
In the baseline, a 200 whose run status is `completed` or `incomplete` SHALL be `accepted`; a 400 for which `is_named_refusal` is true SHALL be `refused` with its status; every other answer (a not-served 400, the generic `invalid request`, a 429, an `overloaded` answer, a failed run) SHALL leave the kind unknown.

#### Scenario: A baseline fact
- **WHEN** the baseline is loaded
- **THEN** `xai/grok-4.3` has `document` refused with 400 (a named route refusal) and `image` unknown, source `baseline`, and `perplexity/deepseek-v4-pro-0813` has `image` unknown (its sweep answer was the generic body) and `document` accepted

#### Scenario: A 429 is never a refusal
- **WHEN** a sweep row answered 429 `upstream model is overloaded` (the misleading answer a 16 by 16 image drew on 2026-11-11 for every xAI image-capable model)
- **THEN** that kind is unknown

#### Scenario: A generic 400 is unknown
- **WHEN** the baseline is built from a sweep row whose image answer is 400 `invalid request`
- **THEN** that kind is unknown, not refused, with no `probed_at`

#### Scenario: grok-4.7 is not recorded as refused
- **WHEN** the baseline is loaded
- **THEN** `xai/grok-4.7` has `image` and `document` accepted with `probed_at` 2026-11-11 (the re-probe of `acceptance/grok-4-7-investigation.md`, which supersedes the 2026-10-30 row for that one model), and `xai/grok-4.3`, `xai/grok-4.20-reasoning` and `xai/grok-4.20-multi-agent` keep `document` refused (re-confirmed 2026-11-11)

#### Scenario: Incomplete is accepted
- **WHEN** the baseline is loaded
- **THEN** `openai/gpt-5-nano` has both kinds accepted although its sweep runs were `incomplete`

#### Scenario: A model that is not served
- **WHEN** the baseline is loaded
- **THEN** `perplexity/nemotron-3-ultra-550b-a55b` has both kinds unknown, not refused

### Requirement: Eligibility for an input probe is per kind
An `available` model SHALL be selected for an input probe when, with `PERPLEXITY_MATRIX_PROBE` `new`, a kind is unknown and its own `retry_after` has passed or is null, or a kind is `refused`, its own `probed_at` is more than 24 hours old (`REFUSAL_TTL`, owner-editable) and its own `retry_after` has passed or is null. Selection also respects the lease and the ten-model and $0.25 limits.

#### Scenario: Baseline answers count
- **WHEN** a model has both kinds answered `accepted` by the baseline
- **THEN** it is not selected for an input probe

#### Scenario: A stale baseline refusal is probed
- **WHEN** the baseline records a kind of a model as refused with a `probed_at` more than 24 hours old, and the stored entry has not attempted that kind
- **THEN** the model is selected for that kind (after its same-round control) exactly as for an own stale refusal; on the packaged baseline that is `xai/grok-4.3`, `xai/grok-4.20-reasoning` and `xai/grok-4.20-multi-agent` for `document`, so the first refresh after the 24 hours costs three controls and three document requests, inside the ten-model and $0.25 limits

#### Scenario: A refused kind in backoff
- **WHEN** a kind was refused 2 days ago but its `retry_after` is still in the future
- **THEN** it is not selected

#### Scenario: One unknown kind
- **WHEN** a model has `image` accepted by the baseline and `document` unknown
- **THEN** it is selected and only the document request is sent after the control

### Requirement: A recent unanswered attempt counts as probed
A kind whose own `last_attempt_at` lies within the current refresh window (the 10-minute lease length) SHALL count as probed even when it is unanswered, and every attempt SHALL stamp `last_attempt_at`.

#### Scenario: An unanswered attempt in this window
- **WHEN** another server attempted a kind a minute ago, left it unanswered, and this server re-reads the file under the lock
- **THEN** this server does not probe that kind again in this refresh

### Requirement: Known kinds include the baseline's for unattempted kinds
A kind counts as known when the stored entry knows it or, for a kind that is not `attempted`, when the baseline answers it; the selection SHALL consult the baseline per kind even when a merge was refused (a truncated list).

#### Scenario: A refused merge
- **WHEN** the live list was truncated so the merge changed nothing and a stored entry has not attempted a kind that the baseline answers
- **THEN** the model is not selected for that kind

### Requirement: Each input probe has its own same-round control
Before an input kind is asked, the task SHALL send a text control request to the model in the SAME round (or reuse the effort probe's control answered in the same round); a control that did not complete leaves every kind of that model unanswered. A control from the baseline or an earlier refresh SHALL NOT be reused.

#### Scenario: A model that stopped being served
- **WHEN** a model's control now answers 400 although a baseline control answered 200 earlier
- **THEN** no kind is recorded refused and the kinds stay unanswered

### Requirement: The input probe request
The probe request SHALL be a fixed 48 by 48 PNG or one-line PDF with a fixed prompt, no tools, `store` false, `max_output_tokens` 150, one attempt and 30 seconds, sent through `probe_request`.

#### Scenario: The request
- **WHEN** an image probe is built
- **THEN** it carries one `input_image` part, `store` false, `max_output_tokens` 150 and no tools

### Requirement: An input probe answers by HTTP status
For input probes only, a 200 whose run status is `completed` or `incomplete` SHALL mean accepted, and a 400 SHALL mean refused only when the control completed AND `is_named_refusal` is true. Every other outcome SHALL leave the kind unanswered.

#### Scenario: Which unanswered outcomes count
- **WHEN** a probe answers any other 400, a 5xx, a timeout, a failed run or 429
- **THEN** the kind is unanswered; all but the 429 count as an unanswered round; a 429 ends that refresh's probing and counts only in `attempts`, never stamping `last_attempt_at`, adding to `unanswered_rounds` or starting a backoff

#### Scenario: Accepted without checking the answer
- **WHEN** an input probe answers 200 with status `completed` or `incomplete`
- **THEN** the kind is accepted whatever the answer says, an `incomplete` event is recorded as `unexpected_response`, and the effort probe's rule is unchanged

#### Scenario: A new model that cannot read images
- **WHEN** a new model completes the control, accepts the document and answers 400 `invalid request` to the image
- **THEN** its inputs list `document` accepted and `image` unknown (unanswered), source `probe`, because the generic body is not a named refusal

#### Scenario: A named refusal
- **WHEN** a new model completes the control and answers 400 `the selected model route does not support this document type or source` to the document
- **THEN** its `document` is refused with 400, source `probe`

#### Scenario: A 429 is never a refusal
- **WHEN** an image probe answers 429 `upstream model is overloaded` (the misleading answer a 16 by 16 image drew on 2026-11-11)
- **THEN** the kind is unanswered, no round counted, never refused, it counts only in `attempts`, and probing stops for that refresh

#### Scenario: A rate-limited kind
- **WHEN** the image request answers 429
- **THEN** probing stops for that refresh, the document request is not sent, and the answers received are kept

#### Scenario: A model that runs out of tokens
- **WHEN** a probe answers 200 with status `incomplete`
- **THEN** the kind is accepted

#### Scenario: A refusal as a failed run
- **WHEN** a document probe answers 200 with run status `failed` and error `refusal`
- **THEN** the kind is unanswered, neither accepted nor refused

### Requirement: One predicate says a model is not served
`matrix.py` SHALL hold `model_not_served(status, message, model=None)`, true for a 400 saying `validation failed: model ... is not supported` and for a 404 or 410 only when the message names the requested `model`. The baseline rules and the input probe SHALL both call it, so no second classifier of a gone model exists.

#### Scenario: The unsupported-model 400
- **WHEN** `model_not_served(400, 'validation failed: model "perplexity/nemotron-3-ultra-550b-a55b" is not supported', "perplexity/nemotron-3-ultra-550b-a55b")` is called
- **THEN** the result is true

#### Scenario: A generic 400 is not served-ness
- **WHEN** `model_not_served(400, "invalid request")` is called
- **THEN** the result is false

#### Scenario: A 404 about something else
- **WHEN** `model_not_served(404, "response not found", "vendor/m")` is called, as for a job poll
- **THEN** the result is false, and with a message naming `vendor/m` a 404 or a 410 is true

### Requirement: One predicate says a refusal is named
`matrix.py` SHALL hold `is_named_refusal(status, message)`, true only for a 400 whose message is in the closed list `NAMED_REFUSALS`, which is exactly `the selected model route does not support this document type or source` until a probe adds a string. The baseline rules and the input probe SHALL call it, and a 429 or any other 400 is never a refusal.

#### Scenario: Named route refusal
- **WHEN** `is_named_refusal(400, "the selected model route does not support this document type or source")` is called
- **THEN** the result is true

#### Scenario: Generic body and overload
- **WHEN** `is_named_refusal(400, "invalid request")` and `is_named_refusal(429, "upstream model is overloaded")` are called
- **THEN** both are false

### Requirement: Unanswered kinds back off per kind
A kind left unanswered in a round (except by a 429, which counts only in `attempts`: see the probe-answer requirement) SHALL add one to ITS `unanswered_rounds` whether or not the model's other kind was answered in that round; at two its `retry_after` SHALL be set 7 days ahead, its count SHALL reset, and no probe of that model for that kind SHALL be sent before then. Only an answer for THAT kind resets its count.

#### Scenario: A model that always fails
- **WHEN** `anthropic/claude-opus-5` answers every document probe with a failed run for two rounds
- **THEN** its document `retry_after` is 7 days ahead and the third refresh sends it no document probe

#### Scenario: One kind answering, the other failing
- **WHEN** a model's image probe is answered in both rounds while its document probe fails in both
- **THEN** the document kind still reaches its backoff

### Requirement: A refusal is not permanent
A `refused` kind (the entry's own, or the baseline's for a kind that is not `attempted`) SHALL be probed again once ITS `probed_at` is more than 24 hours old (the constant `REFUSAL_TTL`, owned by `matrix.py`, owner-editable), under the same limits, and an answer replaces the old one. Independently of probing, the local gate SHALL treat a refusal older than `REFUSAL_TTL` as `unknown`, so a refusal cannot block a model for ever when `PERPLEXITY_MATRIX_PROBE` is `off`.

#### Scenario: The gate reads an old refusal as unknown
- **WHEN** a refusal is older than `REFUSAL_TTL`, or has no readable `probed_at`
- **THEN** `accepts` called with a clock answers `unknown` and the call is sent, while the stored lists, `accepts` without a clock and the `perplexity_models` display are unchanged

#### Scenario: A stale refusal is re-probed
- **WHEN** a model's `document` was refused 25 hours ago and a refresh runs
- **THEN** one document request is sent after a same-round control, and an accepted answer moves the kind to `accepted`

#### Scenario: A fresh refusal is not
- **WHEN** the refusal is 3 hours old
- **THEN** no request is sent for it

#### Scenario: An unanswered re-probe keeps the refusal
- **WHEN** a 25-hour-old refusal is re-probed and the request answers 503 (or times out, or the run fails)
- **THEN** the kind stays refused with its old `probed_at`, `last_attempt_at` is stamped, `unanswered_rounds` rises by one and no request is repeated in the same refresh window

#### Scenario: A 429 counts no round
- **WHEN** a 25-hour-old refusal is already stored, it is re-probed and the request answers 429
- **THEN** the kind stays refused with its old `probed_at`, `attempts` rises by one, `last_attempt_at` is NOT stamped, `unanswered_rounds` and `retry_after` are unchanged, and the next refresh asks again

#### Scenario: An expired refusal does not block the gate
- **WHEN** `PERPLEXITY_MATRIX_PROBE` is `off`, the baseline's refusal of `document` for `xai/grok-4.3` is older than 24 hours and a client asks with that model and a PDF
- **THEN** the call is sent (the gate sees `unknown`), while `accepts` without a clock still answers `no`

### Requirement: Input answers have their own bookkeeping
The refresh task SHALL keep the answers, failed models and pending writes of input probes apart from the effort probe's (their own keys and sets, `inputs.answers` in the file), so a round that failed to finish efforts does not mark inputs failed and the reverse.

#### Scenario: Independent rounds
- **WHEN** a model's effort probe ends with an unanswered level and its input probe completes
- **THEN** the inputs are written as known and the efforts stay incomplete

### Requirement: Input probes are bounded and recorded
Input probes SHALL be recorded as usage events with tool `model_matrix` and no project, through the same `costed_call` caller as the effort probes (no new `record_usage` site), and SHALL count toward the refresh's limits of ten models and $0.25.

#### Scenario: Recorded
- **WHEN** an input probe returns a response
- **THEN** one usage event with tool `model_matrix` and no project is stored for it, and the refresh's cost total includes it

### Requirement: Input probe cost is bounded by the cap check
A model's input probe SHALL cost one control and at most two kind requests, and the $0.25 check before each model SHALL decide whether another model is started (it is a check before a model, not a ceiling on the total), because ten models at the worst cases would cost about $0.24 before any control or effort request.

#### Scenario: The cap check bounds the round
- **WHEN** the reported cost of one refresh's probes (effort and input together) reaches $0.25 before a model starts
- **THEN** no further model is started and the remaining models wait

### Requirement: Measured input probe costs
The README SHALL state input-probe costs only from the sweep of 2026-10-30 (`acceptance/sweep.json`), which measured, per request over the 54 sweep requests, averages of $0.0005 (image) and $0.0021 (document) (including unpriced zeros; priced requests only $0.00056 and $0.0026), worst cases of $0.0037 (image, `google/gemini-3.1-pro-preview`) and $0.0207 (document, `anthropic/claude-fable-5-1`), and $0.10 for the ten dearest models with both kinds.

#### Scenario: Figures stated
- **WHEN** the README's input-probe cost figures are compared with `acceptance/sweep.json`
- **THEN** each figure it states appears in or is computed from the sweep

### Requirement: Callers ask which models accept a kind
The matrix module SHALL expose, pure and without network or database, `accepts(model_id, kinds, matrix=None, now=None)` returning `yes`, `no` or `unknown`, and `models_accepting(kinds, matrix=None)` returning a set of model ids; `kinds` is an iterable of `image` and `document`.

#### Scenario: The answers
- **WHEN** `accepts` is called
- **THEN** it is `yes` when every kind is accepted, `no` when any is refused, else `unknown`; with `now`, a refusal older than `REFUSAL_TTL` is `unknown`; and `models_accepting` holds the `available` models with `yes`, never one whose kind is unknown

#### Scenario: Image-capable set
- **WHEN** the baseline is loaded and `models_accepting({"image"})` is called
- **THEN** the set contains `openai/gpt-6-luna` and `perplexity/sonar` and does not contain `perplexity/deepseek-v4-pro-0813`

#### Scenario: Both kinds
- **WHEN** `models_accepting({"image", "document"})` is called
- **THEN** every id in the result has both kinds in `accepted`, and the result is a subset of `models_accepting({"image"})`

#### Scenario: A model the matrix lacks
- **WHEN** `accepts("vendor/unlisted", {"image"})` is called
- **THEN** the result is `unknown` and the id is in no `models_accepting` result

#### Scenario: A removed model
- **WHEN** a model's `status` is `removed`
- **THEN** it is in no `models_accepting` result

### Requirement: Unknown kinds fall back to the baseline
For a kind that is not `attempted`, `accepts` and `models_accepting` SHALL use the baseline's answer for the same id, so an upgraded deployment is not left with an empty set. An attempted kind without an answer stays unknown even when the baseline answers it. The baseline is read once and cached by `matrix` (`load_baseline()` behind a cache) when no matrix argument is given.

#### Scenario: A file from before this change
- **WHEN** the data directory holds a matrix file whose entries have no `inputs` and `models_accepting({"image"})` is called
- **THEN** the result holds the models the baseline records as accepting images

#### Scenario: Unanswered twice stays unknown
- **WHEN** a stored entry's `document` was attempted and left unanswered twice (so its backoff counter was reset and `retry_after` is set), and the baseline answers `document` as accepted
- **THEN** `accepts` returns `unknown` for `document` for that model

### Requirement: The matrix functions are total and read-only
`accepts` and `models_accepting` SHALL read the matrix with `load` semantics (the file, else the baseline), SHALL never write, and SHALL never raise for any model id; they SHALL raise `ValueError` only for a kind that is not `image` or `document`. An empty `kinds` SHALL give `yes` and every `available` model.

#### Scenario: No writes
- **WHEN** either function is called with no `model_matrix.json` in the data directory
- **THEN** it answers from the baseline and no file is created

#### Scenario: A bad kind
- **WHEN** `models_accepting({"audio"})` is called
- **THEN** it raises `ValueError`

### Requirement: Presets are answered from verified facts only
`preset_accepts(preset, kinds)` SHALL return `yes` for the combinations verified live on 2026-10-30 (images at `fast`, `low` and `medium`; documents at `fast` and `medium`), `unknown` for every other, and never `no`.

#### Scenario: Preset
- **WHEN** `preset_accepts("low", {"image"})` and `preset_accepts("low", {"document"})` are called
- **THEN** the first is `yes` and the second `unknown`

### Requirement: No third-party catalog decides acceptance
`accepts`, `models_accepting` and `preset_accepts` SHALL read only the matrix's own lists (a probe or the packaged sweep). A third-party aggregator's modalities (LLM Stats: text, image, audio and video only, per maker, no document modality) MAY be printed by the acceptance scripts as an advisory cross-check and SHALL NOT be stored in the matrix or make any answer `yes`.

#### Scenario: An aggregator claims image support
- **WHEN** an aggregator lists `image` for a model whose matrix inputs are unanswered
- **THEN** `accepts(model, {"image"})` is `unknown`

#### Scenario: No document modality
- **WHEN** the cross-check runs for the `document` kind
- **THEN** it prints nothing for it, because the aggregator has no document modality

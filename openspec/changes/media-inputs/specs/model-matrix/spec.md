# model-matrix Specification

## MODIFIED Requirements

### Requirement: Each model entry holds prices and availability
An entry SHALL hold the model's provider, its pricing (input, output, cache read and cache write per million tokens, or null), `status` (`available` or `removed`), `first_seen`, `last_seen`, `probing_until` (a UTC time or null), its `efforts` and its `inputs`.

#### Scenario: An entry
- **WHEN** a listed model is merged
- **THEN** its entry holds the provider, the four prices or null, `status` `available`, `first_seen`, `last_seen` and `probing_until` null

#### Scenario: An entry's inputs
- **WHEN** a listed model is merged and the baseline holds no row for it
- **THEN** its entry holds `inputs` with nothing accepted or refused

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

### Requirement: A probe is bounded, recorded and not duplicated
Each probe request SHALL be one attempt with no retry, and every one that returns a response or fails with an error SHALL be recorded as a usage event. A refresh SHALL stop probing after ten models or when the reported cost so far reaches $0.25, checked before each model. Before probing a model, a task SHALL write a 10-minute `probing_until` lease on it under the lock and clear it afterwards, and SHALL skip any model whose lease is unexpired or already probed.

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

## ADDED Requirements

### Requirement: This capability owns the modality data
The model matrix is the only owner of which input kinds a model accepts. Kinds are `image` and `document` only (text is implicit; audio and video are refused before any router sees them). Every other part of the server, including the router of `routing-v2`, SHALL read modalities through `accepts`, `models_accepting` and `preset_accepts` and SHALL NOT keep its own modality table.

#### Scenario: One source
- **WHEN** `rg "input_modalities|modalit" src/ data/` is run after the change
- **THEN** every match is in `matrix.py`, the baseline, `perplexity_models` output text or a comment

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
The baseline SHALL give every model an `inputs` record from the live sweep of 2026-10-30 (one image and one document request per model, `store` false). Every answered kind carries source `baseline` and `probed_at` `2026-10-30T00:00:00Z`.

#### Scenario: Every model has inputs
- **WHEN** the baseline is loaded
- **THEN** all 54 entries hold an `inputs` record

#### Scenario: The sweep counts
- **WHEN** the baseline is loaded
- **THEN** images are accepted for 47 models, refused for 6 and unknown for 1, and documents are accepted for 44, refused for 5 and unknown for 5

### Requirement: The baseline's answer rules
In the baseline, a 200 whose run status is `completed` or `incomplete` SHALL be `accepted`; a 400 whose message says `validation failed: model ... is not supported` is UNKNOWN (the model is not served; it did not refuse the kind); any other 400 is `refused` with its status; a persistent 429, an `overloaded` answer or a failed run leaves the kind unknown.

#### Scenario: A baseline fact
- **WHEN** the baseline is loaded
- **THEN** `perplexity/deepseek-v4-pro-0813` has `image` refused with 400 and `document` accepted, source `baseline`

#### Scenario: Incomplete is accepted
- **WHEN** the baseline is loaded
- **THEN** `openai/gpt-5-nano` has both kinds accepted although its sweep runs were `incomplete`

#### Scenario: A model that is not served
- **WHEN** the baseline is loaded
- **THEN** `perplexity/nemotron-3-ultra-550b-a55b` has both kinds unknown, not refused

### Requirement: Eligibility for an input probe is per kind
An `available` model SHALL be selected for an input probe when, with `PERPLEXITY_MATRIX_PROBE` `new`, a kind is unknown and its own `retry_after` has passed or is null, or a kind is `refused`, its own `probed_at` is more than 14 days old and its own `retry_after` has passed or is null. Selection also respects the lease and the ten-model and $0.25 limits.

#### Scenario: Baseline answers count
- **WHEN** a model has both kinds answered by the baseline
- **THEN** it is not selected for an input probe

#### Scenario: A refused kind in backoff
- **WHEN** a kind was refused 15 days ago but its `retry_after` is still in the future
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
For input probes only, a 200 whose run status is `completed` or `incomplete` SHALL mean accepted, without checking the answer, and the usage event of an `incomplete` run is recorded with the status `agent_response_status` gives it (`unexpected_response`); the effort probe's rule is unchanged. A 400 SHALL mean refused only when the control completed. A 5xx, a timeout or a 200 whose run `failed` SHALL leave the kind unanswered. A 429 SHALL end that refresh's probing.

#### Scenario: A new model that cannot read images
- **WHEN** a new model completes the control, accepts the document and answers 400 to the image
- **THEN** its inputs list `document` accepted and `image` refused with 400, source `probe`

#### Scenario: A rate-limited kind
- **WHEN** the image request answers 429
- **THEN** probing stops for that refresh, the document request is not sent, and the answers received are kept

#### Scenario: A model that runs out of tokens
- **WHEN** a probe answers 200 with status `incomplete`
- **THEN** the kind is accepted

#### Scenario: A refusal as a failed run
- **WHEN** a document probe answers 200 with run status `failed` and error `refusal`
- **THEN** the kind is unanswered, neither accepted nor refused

### Requirement: Unanswered kinds back off per kind
A kind left unanswered in a round SHALL add one to ITS `unanswered_rounds` whether or not the model's other kind was answered in that round; at two its `retry_after` SHALL be set 7 days ahead, its count SHALL reset, and no probe of that model for that kind SHALL be sent before then. Only an answer for THAT kind resets its count.

#### Scenario: A model that always fails
- **WHEN** `anthropic/claude-opus-5` answers every document probe with a failed run for two rounds
- **THEN** its document `retry_after` is 7 days ahead and the third refresh sends it no document probe

#### Scenario: One kind answering, the other failing
- **WHEN** a model's image probe is answered in both rounds while its document probe fails in both
- **THEN** the document kind still reaches its backoff

### Requirement: A refusal is not permanent
A `refused` kind SHALL be probed again once ITS `probed_at` is more than 14 days old, under the same limits, and the result replaces the old one. A refusal is inferred from an HTTP 400 whose generic body (`invalid request`) several unrelated mistakes share, so it is a likely answer and not a proof; the local gate uses `no` until a re-probe replaces it, which is why the re-probe exists.

#### Scenario: A stale refusal is re-probed
- **WHEN** a model's `image` was refused 15 days ago and a refresh runs
- **THEN** one image request is sent after a same-round control, and an accepted answer moves the kind to `accepted`

#### Scenario: A fresh refusal is not
- **WHEN** the refusal is 3 days old
- **THEN** no request is sent for it

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
A model's input probe SHALL cost one control and at most two kind requests, and the $0.25 check before each model SHALL bound a round, because ten models at the worst cases would cost about $0.24 before any control or effort request.

#### Scenario: The cap check bounds the round
- **WHEN** the reported cost of one refresh's probes (effort and input together) reaches $0.25 before a model starts
- **THEN** no further model is started and the remaining models wait

### Requirement: Measured input probe costs
The README SHALL state input-probe costs only from the sweep of 2026-10-30 (`acceptance/sweep.json`), which measured, per request over the 54 sweep requests, averages of $0.0005 (image) and $0.0021 (document) (including unpriced zeros; priced requests only $0.00056 and $0.0026), worst cases of $0.0037 (image, `google/gemini-3.1-pro-preview`) and $0.0207 (document, `anthropic/claude-fable-5-1`), and $0.10 for the ten dearest models with both kinds.

#### Scenario: Figures stated
- **WHEN** the README's input-probe cost figures are compared with `acceptance/sweep.json`
- **THEN** each figure it states appears in or is computed from the sweep

### Requirement: The router asks which models accept a kind
The matrix module SHALL expose, pure and without network or database, `accepts(model_id, kinds, matrix=None)` returning `yes`, `no` or `unknown`, and `models_accepting(kinds, matrix=None)` returning a set of model ids; `kinds` is an iterable of `image` and `document`. `accepts` is `yes` when every kind is accepted, `no` when any is refused, else `unknown`. `models_accepting` holds the `available` models with `yes`, never one whose kind is unknown.

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

### Requirement: The router functions are total and read-only
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

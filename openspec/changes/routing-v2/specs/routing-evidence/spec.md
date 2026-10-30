# Spec Delta

## ADDED Requirements

### Requirement: Benchmark evidence is one versioned file shipped in the package
The server SHALL ship `routing_evidence.json` in the package (`version` 1, `as_of`, `task_classes`, `benchmarks`, a `shortlist`, `fallbacks` and per-model `scores`; the file holds no modality facts, which belong to the model matrix). A file of that name in `PERPLEXITY_DATA_DIR` SHALL take precedence and SHALL never be written by the server. An invalid, unreadable or unknown-version file SHALL be replaced by the packaged one with one warning.

#### Scenario: Packaged default
- **WHEN** the server starts with no `routing_evidence.json` in the data directory
- **THEN** the packaged evidence is used and every shortlist id and the default fallback model have an entry under `models`

#### Scenario: Data directory override
- **WHEN** the data directory holds a valid `routing_evidence.json` with a different shortlist
- **THEN** that file is used, and the server does not modify or rename it

#### Scenario: A corrupt override
- **WHEN** the data directory file holds text that is not JSON
- **THEN** the packaged evidence is used, one warning names the file, and the file is left as it was

#### Scenario: A newer version
- **WHEN** the file has `version` 2
- **THEN** the packaged evidence is used with one warning

#### Scenario: Empty scores are the shipped state
- **WHEN** every model entry has an empty `scores` object
- **THEN** the file is valid and no model is eligible for any class

#### Scenario: Fallback model without an entry
- **WHEN** `fallbacks.default.model` has no entry under `models`
- **THEN** the file is invalid and the packaged evidence is used with one warning

### Requirement: Evidence is read lazily and warned about in dynamic mode only
The evidence SHALL be loaded on first use through one holder on the server's application context (never at server construction, so `perplexity-pro help` and the schema builder read no file). In `dynamic` mode the serving process SHALL read it once at start and emit one warning when `as_of` is more than 90 days before the start date and one when it holds no verified score. In `standard` and `custom` mode it SHALL never be read, and a one-shot command emits no startup warning.

#### Scenario: Help touches nothing
- **WHEN** `perplexity-pro help` runs
- **THEN** no evidence file is read and no data directory is created

#### Scenario: Old evidence
- **WHEN** a serving process starts in `dynamic` mode with `as_of` 91 days before the start date
- **THEN** one warning names the date and routing is unchanged

#### Scenario: No verified evidence
- **WHEN** a serving process starts in `dynamic` mode with the packaged empty-scores evidence
- **THEN** one warning says no verified evidence is loaded and every nameless call will fall back

#### Scenario: Other modes read nothing
- **WHEN** a serving process starts in `standard` mode with a corrupt data-directory evidence file
- **THEN** no evidence is read and no warning about it is logged

### Requirement: Every score carries its source and date, and an unverified score is never used
A score SHALL be a number from 0 to 100 with an `https` `source_url`, an `as_of` date, a `basis` (`independent` or `vendor`), a `harness` (text or null) and a `verified_at` date or null; a missing field, or a `verified_at` before `as_of` or after the load date (UTC), invalidates the file. A null `verified_at` is ignored by selection. A benchmark's version is part of its id (`terminal_bench_2_1`).

#### Scenario: An unsourced figure
- **WHEN** the file holds a score with no `source_url`
- **THEN** the file is invalid and the packaged evidence is used with one warning naming the model and benchmark

#### Scenario: An unverified figure is ignored
- **WHEN** a shortlist model's only score for a class's benchmark has `verified_at` null
- **THEN** selection treats the model as having no score for that benchmark

#### Scenario: Out-of-range score
- **WHEN** a score is 101 or negative
- **THEN** the file is invalid

#### Scenario: Verified before it was recorded
- **WHEN** a score has `as_of` 2026-10-20 and `verified_at` 2026-10-10, or a `verified_at` in the future
- **THEN** the file is invalid

#### Scenario: Shortlist entry without a model entry
- **WHEN** the shortlist names a model id that has no entry under `models`
- **THEN** the file is invalid

#### Scenario: A different version does not count
- **WHEN** the `coding` class lists `terminal_bench_2_1` and a model's only Terminal-Bench score is under `terminal_bench_4_0`
- **THEN** the model has no score for the class's benchmark and is not eligible for `coding`

### Requirement: Classes reference known benchmarks
A task class SHALL list only benchmark ids that exist in `benchmarks`; a file where one does not is invalid.

#### Scenario: A class lists an unknown benchmark
- **WHEN** the `coding` class lists `terminal_bench_9` and `benchmarks` has no such id
- **THEN** the file is invalid and the packaged evidence is used with one warning

### Requirement: A task class is scored by the mean of its benchmarks
A model's score for a task class SHALL be the arithmetic mean of its verified scores for every benchmark id the class lists, and a model lacking a verified score for any of them SHALL not be eligible for that class. The classes and their benchmark ids SHALL come from the file, so editing them needs no code change.

#### Scenario: Two benchmarks
- **WHEN** the `coding` class lists two benchmarks and a model has verified scores 60 and 70
- **THEN** its coding score is 65

#### Scenario: A benchmark missing
- **WHEN** a model has a verified score for one of the two coding benchmarks only
- **THEN** it is not eligible for `coding` and stays eligible for a class whose benchmarks it has

#### Scenario: Class edited in the file
- **WHEN** the data directory file moves a benchmark id from `reasoning` to `coding`
- **THEN** selection uses the new membership with no code change

### Requirement: Selection is deterministic, pure and offline
The selector SHALL be a pure function of the task class, the tier, the tool (`ask`, `chat` or `research`), `search`, the matrix snapshot, the evidence, the required input kinds and the margin passed to it (no network, database, file, clock or randomness), with the same result in every process. Contenders are eligible models within the margin of the best score, in exact decimal arithmetic; the lowest blended price (3 parts input, 1 part output) wins, then the higher score, then the smaller id.

#### Scenario: Cheaper within the margin
- **WHEN** the margin is 3 and model A scores 80 at a blended 6.0 while model B scores 78 at a blended 1.0
- **THEN** B is chosen

#### Scenario: Outside the margin
- **WHEN** the margin is 3 and model A scores 80 while the cheaper model B scores 76
- **THEN** A is chosen

#### Scenario: Margin boundary in decimal
- **WHEN** the margin is 3, the best score is 80.3 and model B scores exactly 77.3
- **THEN** B is a contender, as it is for 80 and 77

#### Scenario: Margin zero
- **WHEN** the margin is 0 and two models differ by 0.5 points
- **THEN** the higher score wins whatever the prices

#### Scenario: Full tie
- **WHEN** two contenders have the same score and the same blended price
- **THEN** the smaller model id wins, whatever the order of the shortlist

#### Scenario: Unknown price
- **WHEN** the best-scoring model has a null output price in the matrix
- **THEN** it is not eligible and is never chosen

#### Scenario: Same inputs, same result
- **WHEN** selection runs twice on equal inputs, in one process or two
- **THEN** the results are equal

### Requirement: Eligibility
A model SHALL be eligible for a class when it is shortlisted, `available` in the matrix, has both prices, the matrix says it accepts every required kind (`accepts(model, kinds) == yes`, always true for an empty set) and has a verified score for every benchmark of the class.

#### Scenario: Each condition excludes
- **WHEN** a model is off the shortlist, `removed`, unpriced, is not `yes` for a required kind (`no`, `unknown` or unprobed) or lacks a class score
- **THEN** it is not eligible, each condition on its own

### Requirement: The margin is named and configurable
The margin SHALL default to 3 points and be overridable by `PERPLEXITY_ROUTER_MARGIN`, a number from 0 to 20; any other value SHALL fail startup naming the variable. The variable SHALL be ignored with one warning outside `dynamic` mode and not validated there.

#### Scenario: Default margin
- **WHEN** the server starts in `dynamic` mode with the variable unset
- **THEN** the margin is 3

#### Scenario: Out of range
- **WHEN** `PERPLEXITY_ROUTER_MARGIN` is `25` in `dynamic` mode
- **THEN** startup fails naming the variable and the range 0 to 20

#### Scenario: Unused outside dynamic mode
- **WHEN** the mode is `standard` and the variable is set to `abc`
- **THEN** the server starts and logs one warning naming the variable

### Requirement: The tier gives a target effort that the model's accepted levels clip
The target level SHALL be `low` for tier `light`, `medium` for `standard`, and for `complex` `medium` in ask and chat and `high` in research; `xhigh` is never automatic. The level sent SHALL be the highest accepted level not above the target, else the lowest accepted, else none (no level accepted, never probed, or absent from the matrix, a pin included). The tier SHALL NOT change the chosen model, so for ask and chat `standard` and `complex` differ only in the classification recorded.

#### Scenario: Accepted target
- **WHEN** the tier is `standard`, the tool is ask and the chosen model accepts `medium`
- **THEN** the effort is `medium`

#### Scenario: Target refused
- **WHEN** the target is `medium` and the model's accepted levels are `high` and `xhigh` only
- **THEN** the effort is `high`

#### Scenario: Highest not above the target
- **WHEN** the target is `medium` and the model accepts `minimal` and `high`
- **THEN** the effort is `minimal`

#### Scenario: No levels accepted
- **WHEN** the chosen model's probed efforts accept no level
- **THEN** no effort is sent

#### Scenario: Never probed or unknown to the matrix
- **WHEN** the chosen or pinned model's efforts are `unprobed`, or the matrix has no entry for it
- **THEN** no effort is sent

#### Scenario: Ask and chat cap
- **WHEN** a `complex` prompt is routed for ask or chat
- **THEN** the effort is at most `medium`

#### Scenario: Research reaches high
- **WHEN** a `complex` prompt is routed for research
- **THEN** the target is `high` and `xhigh` is not chosen

#### Scenario: Tier does not pick the model
- **WHEN** the same prompt text is routed once as tier `light` and once as `complex`
- **THEN** the chosen model is the same and only the effort differs

### Requirement: An unavailable choice falls back in a fixed order
When no model is eligible, ask and chat SHALL try `fallbacks.default` (`openai/gpt-6-luna` at `low` as shipped, subject to the same `accepts` test through the matrix and clipped like any level: the highest accepted level not above `low`, else no effort) and then the tier's documented preset. A rung whose model is not `available` SHALL be skipped, and the result has `selected_by` `fallback` and a reason naming the rung.

#### Scenario: No eligible model
- **WHEN** every shortlist model is `removed` and `openai/gpt-6-luna` is `available`
- **THEN** the call runs `openai/gpt-6-luna` at `low` with `selected_by` `fallback`

#### Scenario: Fallback model removed
- **WHEN** no shortlist model is eligible and `openai/gpt-6-luna` is `removed`
- **THEN** the call runs the documented preset of its tier and no model

#### Scenario: The fallback model lacks low
- **WHEN** the fallback model accepts `medium` and `high` but not `low`
- **THEN** no reasoning effort is sent for it

#### Scenario: Search off reaches the preset rung
- **WHEN** a call with `search` false finds every model rung unavailable
- **THEN** it fails with `invalid_request` naming `search`, saying a preset always searches and no routed model is available, and nothing is sent

#### Scenario: Media reaches the preset rung
- **WHEN** the required kinds include `image`, no model rung accepts it and the tier's preset is not `yes` for `image` in the matrix
- **THEN** the call fails with `invalid_request` naming `image` and the preset rung is not used

#### Scenario: Unverified evidence
- **WHEN** the evidence holds no verified score
- **THEN** every nameless call falls back

### Requirement: Research falls back to its preset
When no model is eligible for a routed research run, the router SHALL use the documented preset of its tier (`medium` for `light` and `standard`, `high` for `complex`) and never `fallbacks.default`, so a deep run is never silently replaced by a cheap model.

#### Scenario: Research never falls back to the default model
- **WHEN** no shortlist model is eligible for a routed research run and `openai/gpt-6-luna` is `available`
- **THEN** the run names preset `medium` (or `high` for a `complex` prompt) and no model

### Requirement: The preset rung has conditions
The preset rung SHALL name no model and SHALL be allowed only when `search` is not false (a preset always searches) and, when media is required, only when the matrix says the tier's preset accepts every required kind (`preset_accepts(preset, kinds) == yes`); otherwise it is not allowed.

#### Scenario: Preset rung allowed
- **WHEN** no model rung is available, no media is required and `search` is not false
- **THEN** the documented preset of the tier runs

#### Scenario: Preset rung with media
- **WHEN** no model rung is available, `image` is required and `preset_accepts` says `yes` for the tier's preset
- **THEN** the preset runs; when it says `no` or `unknown` the call fails with `invalid_request` naming `image`

### Requirement: A media requirement narrows the candidates
The selector SHALL take a set of required input kinds (`image`, `document`; empty means text only) and SHALL treat a model, and each fallback rung, as eligible only when the model matrix (whose input facts `media-inputs` owns) answers `yes` to `accepts(model, kinds)`; `no`, `unknown` and unprobed are never substituted. With no eligible model or rung the call SHALL fail with `invalid_request` naming the kinds. The final attachment gate belongs to `media-attachments`.

#### Scenario: Empty set
- **WHEN** a call requires no kinds
- **THEN** modality does not exclude any model

#### Scenario: Image required
- **WHEN** the required set is `image` and only some shortlist models answer `yes`
- **THEN** only those models are candidates, and the winner is the cheapest within the margin among them

#### Scenario: Unknown is not substituted
- **WHEN** the matrix answers `unknown` for the best-scoring model and `yes` for another
- **THEN** the other model is chosen

#### Scenario: Nothing accepts the document
- **WHEN** no shortlist model and no fallback rung answers `yes` for `document` and `document` is required
- **THEN** the call fails with `invalid_request` naming `document` and no request is sent

### Requirement: The router stays correct when the catalog changes
Selection SHALL read the matrix at call time, so a model that becomes `removed`, a changed price, a newly refused level or a newly listed model SHALL change the next call's result with no code or file edit; a model listed in the catalog but absent from the shortlist SHALL never be chosen.

#### Scenario: Winner removed
- **WHEN** the previously chosen model becomes `removed` in the matrix
- **THEN** the next call chooses the best of the remaining contenders, or the fallback

#### Scenario: Price rises
- **WHEN** the winner's price rises above another contender's
- **THEN** the other contender wins the next call

#### Scenario: A new model appears
- **WHEN** the matrix gains a model that is not on the shortlist
- **THEN** it is never chosen

### Requirement: Router status and drift are visible
`perplexity_models` SHALL report, in `dynamic` mode, one `evidence` line of the evidence `as_of`, the shortlist size and the number of eligible shortlist models per task class. The offline suite SHALL fail when a shortlist id or a fallback model is absent from the packaged matrix baseline, and a `live`-marked test SHALL fail when one is absent from the live catalog.

#### Scenario: Evidence line
- **WHEN** a client calls `perplexity_models` against a `dynamic` server
- **THEN** the routing section has an `evidence` line with the `as_of` date, the shortlist size and a count for each of `coding`, `reasoning` and `browsing`

#### Scenario: Shortlist drift
- **WHEN** a shortlist id is not a key of the packaged matrix baseline
- **THEN** the offline test suite fails

### Requirement: The reason names the rule and never the prompt
A routed call's `reason` SHALL be at most 120 ASCII characters built from constants and counts (the task class, the number of contenders, the rule, the fallback rung, `held` or `pinned`), and SHALL NOT contain any text from the prompt.

#### Scenario: Reason content
- **WHEN** a prompt containing the string `hunter2` is routed
- **THEN** the reason names the class and the rule and does not contain `hunter2`

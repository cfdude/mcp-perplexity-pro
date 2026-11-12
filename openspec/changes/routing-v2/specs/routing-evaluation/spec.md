# routing-evaluation Specification

## ADDED Requirements

### Requirement: The router is merged only when an in-branch evaluation passes every pre-registered threshold
The branch SHALL carry a reproducible evaluation (harness `tests/routing_eval/`, report `openspec/changes/routing-v2/acceptance/evaluation.md`), and the routed selection SHALL NOT be merged unless the report shows PASS for every threshold. Any FAIL, INVALID or missing threshold means the branch stays unmerged. The evaluation is a merge gate of this change and is not deferred to another epic.

#### Scenario: All thresholds pass
- **WHEN** `acceptance/evaluation.md` records PASS for every threshold and its recorded git head is the head being merged
- **THEN** the merge task may proceed and the pull request description quotes the report

#### Scenario: One threshold fails
- **WHEN** the report records FAIL for the cost threshold
- **THEN** the routed selection is not merged and the branch stays open

#### Scenario: A stale report
- **WHEN** a commit that touches `src/` lands after the head recorded in the report
- **THEN** the report is stale and the merge task treats it as missing until the harness is re-run

### Requirement: The thresholds are written down before any run
The thresholds SHALL be committed in this spec, in `tests/routing_eval/thresholds.py` and in `acceptance/preregistration.md` (with the registering commit) BEFORE any scored run, and SHALL NOT change after a result exists. A change of margin, class mapping, shortlist or evidence after a run SHALL start a new numbered run reported beside every earlier one. The owner may edit thresholds only before registration.

#### Scenario: The registered values
- **WHEN** the thresholds are registered
- **THEN** they are T0 at least 12 prompts per class; T1a decision p95 under 5 ms; T1b 0 added network calls; T2a median added wall time under 50 ms; T2b live latency ratio at most 1.10; T2c cold start under 100 ms; T3a `tools/list` at most 59779; T3b `routing` object at most 400 bytes; T3c `input` byte-identical; T4a cost at most 0.75 of the strongest arm; T4b at most 4.0 of the cheapest arm; T5a quality at least strongest minus 0.05; T5b per class minus 0.10; T5c judge agreement at least 0.90

#### Scenario: Registered before the run
- **WHEN** a live arm is started and `acceptance/preregistration.md` is not committed, or the thresholds module differs from it
- **THEN** the harness refuses to run and spends nothing

#### Scenario: A threshold edited after a result
- **WHEN** a threshold value changes after a scored run exists for the same configuration
- **THEN** the offline test that pins the thresholds fails

#### Scenario: Tuning is a new run
- **WHEN** the margin is changed after run 1 fails
- **THEN** run 2 is recorded with its own configuration hash beside run 1, and a PASS counts only for the run whose configuration is the head being merged

### Requirement: The labeled prompt set is fixed, large enough and pinned by hash
The set SHALL be `tests/fixtures/routing_prompts.json`, extended: each routed prompt carries its tier label, a `task` label and an `eval` object holding a `check` or a `rubric` of at most five binary criteria, with at least 12 such prompts per class. The SHA-256 of its canonical JSON SHALL be committed in `acceptance/prompt_set.sha256` before any live run, and a test SHALL fail when the file no longer matches.

#### Scenario: Class counts
- **WHEN** the offline test reads the set
- **THEN** each of `coding`, `reasoning` and `browsing` has at least 12 prompts with an `eval` object, and every tier label of the earlier set is unchanged

#### Scenario: The set changed
- **WHEN** a prompt is edited after `acceptance/prompt_set.sha256` was committed
- **THEN** the hash test fails until a new run is registered

#### Scenario: A checkable answer
- **WHEN** a prompt has a `number` check with tolerance 0.5 and the answer says 41.7 where the label is 42
- **THEN** the harness scores the prompt 1 and executes no code from the answer

#### Scenario: Answers do not drift
- **WHEN** a browsing prompt is authored
- **THEN** its answer is a dated fact or a rubric that names no changing value

### Requirement: The routing decision is cheap and adds no network call
The harness SHALL time `routing.resolve` plus `routing_select.select` in `dynamic` mode, offline, over every prompt of the set, and T1a passes when p95 is under 5 ms. T1b passes only when a routed ask makes the same number of upstream requests as the ask naming the configured model, none of them a models listing.

#### Scenario: Timing
- **WHEN** the microbenchmark runs at least 200 repetitions per prompt after 20 discarded warm-up calls
- **THEN** the report holds p50, p95 and p99 in milliseconds, the Python version and the machine, and T1a is PASS only for a p95 under 5

#### Scenario: Request count
- **WHEN** a routed ask runs against a counting stub
- **THEN** exactly one upstream request is made, none of it a models listing, and T1b is PASS

#### Scenario: A mutation
- **WHEN** the selector is changed to fetch the catalog on each call
- **THEN** the request-count test goes red

### Requirement: A routed call adds little wall time against naming the model
T2a SHALL pass when, over at least 200 interleaved pairs against the same instant stub upstream, the median added time of a routed ask over an ask naming the configured model is under 50 ms; T2c when the first routed call of a fresh process takes under 100 ms; T2b when the live routed arm's median latency is at most 1.10 times the strongest arm's.

#### Scenario: Paired overhead
- **WHEN** the paired run completes after a warm-up
- **THEN** the report holds the median, p95 and pair count, and T2a is PASS only for a median under 50 ms

#### Scenario: Cold start
- **WHEN** a fresh process serves its first routed ask
- **THEN** the time is recorded and T2c is PASS only under 100 ms

#### Scenario: Decisions classifier reported apart
- **WHEN** the classifier is `decisions`
- **THEN** its added time is a separate line, it stays opt-in, and it does not count toward T2a

### Requirement: A routed call adds no tokens and little response size
T3c SHALL pass only when the routed upstream request's `input` is byte-identical to the explicit-model request's for the same prompt and the only differences are the `model` value and the optional `reasoning.effort` key. T3b SHALL pass when the largest serialized `routing` object of the run is at most 400 bytes. T3a SHALL pass when each of the three measured servers' `tools/list` is at most 59779 bytes.

#### Scenario: Identical input
- **WHEN** the same prompt is asked routed and with the model named
- **THEN** the two `input` values are byte-identical and no `instructions` text was added

#### Scenario: Routing object size
- **WHEN** the largest `routing` object of the run is serialized
- **THEN** it is at most 400 bytes and the report records the byte count

#### Scenario: Tools list
- **WHEN** the default, dynamic and dynamic-with-Decisions servers are measured
- **THEN** each is at most 59779 bytes

### Requirement: Routed spend is measured against two baselines
The live run SHALL send every prompt through three arms of identical request shape differing only in model (and its D5 effort): routed, strongest (highest mean of its verified class scores) and cheapest (lowest blended price among available shortlist models). Spend SHALL be the sum of recorded `cost_usd` per arm. T4a passes when routed spend is at most 0.75 times the strongest arm's, T4b when it is at most 4.0 times the cheapest arm's.

#### Scenario: Cost saved against the strongest model
- **WHEN** the strongest arm costs 1.00 USD and the routed arm 0.70
- **THEN** T4a is PASS, and with 0.80 it is FAIL

#### Scenario: Not just the cheapest model
- **WHEN** the cheapest arm costs 0.10 USD and the routed arm 0.45
- **THEN** T4b is FAIL

#### Scenario: Unknown cost
- **WHEN** one event of an arm has cost source `none`
- **THEN** that arm is INVALID, the cost thresholds are INVALID and nothing is merged

### Requirement: Quality is scored by checks and a blind judge
A prompt's quality SHALL be 1 or 0 for a `check` and the fraction of rubric criteria met for a rubric, each criterion judged by one `perplexity_decide` `choice` question with arm labels removed and answers shuffled by a fixed seed, using one recorded judge model. T5a passes when the routed overall mean is at least the strongest arm's minus 0.05, T5b when each class is within 0.10, T5c when the judge agrees with the checks on at least 0.90 of the checkable answers.

#### Scenario: Within tolerance
- **WHEN** the strongest arm's mean is 0.88 and the routed arm's 0.84
- **THEN** T5a is PASS, and with 0.82 it is FAIL

#### Scenario: One class lags
- **WHEN** the routed arm trails the strongest arm by 0.12 on `coding`
- **THEN** T5b is FAIL although the overall score passes

#### Scenario: An unreliable judge
- **WHEN** the judge agrees with the checks on 0.85 of the checkable answers
- **THEN** T5c is FAIL and no rubric score is used to pass anything

### Requirement: Live runs are budgeted and bounded
All live runs recorded in the branch (arms, judge, re-runs) SHALL together spend under 5 USD, enforced from usage events with caps of 2.50 for the strongest arm, 1.00 routed, 0.50 cheapest, 0.50 judge and 0.50 reserve. The harness SHALL stop before a request that could exceed a cap and mark the run INCOMPLETE, which passes nothing. It SHALL run on a scratch instance and record digests under `acceptance/eval-runs/`, never the key.

#### Scenario: A cap is reached
- **WHEN** the strongest arm reaches its cap before the set is finished
- **THEN** the run is INCOMPLETE and every threshold needing that arm is INVALID

#### Scenario: Reconciliation
- **WHEN** the run ends
- **THEN** `perplexity_usage` totals for the scratch data directory equal the sum in the report, to the nano-USD

#### Scenario: Secrets
- **WHEN** the `acceptance/eval-runs/` files are scanned
- **THEN** none holds a key-shaped string

### Requirement: An evaluation with no verified evidence is invalid, never a pass
The shipped evidence has empty scores, so with it the router always falls back and cannot beat the baseline. The harness SHALL refuse to score a live run unless verified scores make the router, not the fallback chain, choose for at least 75 percent of the set; otherwise the run is INVALID. If, with verified evidence, T4a, T4b, T5a or T5b FAIL, the outcome SHALL be DO NOT MERGE the routed selection.

#### Scenario: The shipped state
- **WHEN** the harness starts against the packaged evidence with empty scores
- **THEN** it reports INVALID because the router would only measure the fallback, and no live request is sent

#### Scenario: Too many fallbacks
- **WHEN** verified evidence exists but the router chooses for 60 percent of the set
- **THEN** the run is INVALID and the report names the fallback share

#### Scenario: Sourced evidence, failed stick
- **WHEN** the evidence is verified and the cost threshold FAILs
- **THEN** the report's verdict is DO NOT MERGE and the branch stays unmerged

### Requirement: The report states one verdict line per threshold
`acceptance/evaluation.md` SHALL be generated by the harness and hold, per run, the git head, the SHA-256 of the prompt set, thresholds and evidence, the models of the three arms, spend per arm, one line `T4a PASS|FAIL|INVALID: <measured> against <threshold>` per threshold, the fallback share and a final verdict `MERGE ALLOWED` or `DO NOT MERGE`. The pull request SHALL quote it and the merge task SHALL depend on `MERGE ALLOWED`.

#### Scenario: Verdict lines
- **WHEN** the report is generated
- **THEN** it has a line for each of T0, T1a, T1b, T2a, T2b, T2c, T3a, T3b, T3c, T4a, T4b, T5a, T5b and T5c, and the verdict is `MERGE ALLOWED` only when every line is PASS

#### Scenario: Quoted in the pull request
- **WHEN** the pull request is opened
- **THEN** its description quotes those lines and the verdict

### Requirement: No savings or quality claim is made before the report passes
No document, help text, tool description, README, CHANGELOG or pull request SHALL state a savings, speed or quality figure for routing before the report records `MERGE ALLOWED`; after it does, a document MAY quote the measured figures with the report as its source and the run's date.

#### Scenario: Before the report
- **WHEN** the documentation task runs and the report has any FAIL or INVALID
- **THEN** no document quotes a savings figure

#### Scenario: After a pass
- **WHEN** the report records `MERGE ALLOWED`
- **THEN** the README may quote the measured percentages and names `acceptance/evaluation.md` as the source

### Requirement: A failed evaluation leaves media-inputs shippable alone
When the verdict is `DO NOT MERGE` or INVALID, the routed selection, its evidence file and migration `0006` SHALL NOT be merged, and `media-inputs` SHALL remain deliverable alone, because it owns the modality facts and the attachment gate and takes nothing from migration `0006`. The unwind of task 7.8 SHALL name exactly the routing-owned pieces it built on and be limited to them.

#### Scenario: Migration 0006 is not needed
- **WHEN** `media-inputs` ships without `routing-v2`
- **THEN** the revision head is `0005` and no media code reads `chat_messages.tier`, `chat_messages.routed_model` or `research_jobs.effort`

#### Scenario: The gate without the router
- **WHEN** `media-inputs` ships without `routing-v2`
- **THEN** the attachment gate checks the final route of the existing resolve (explicit model, pin, tier model, default, or a preset) and no router substitution or held-model rule exists

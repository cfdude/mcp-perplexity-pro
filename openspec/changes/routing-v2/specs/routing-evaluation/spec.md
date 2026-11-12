# routing-evaluation Specification

## ADDED Requirements

### Requirement: The router is merged only when an in-branch evaluation passes every pre-registered threshold
The branch SHALL carry a reproducible evaluation (harness `tests/routing_eval/`, report `openspec/changes/routing-v2/acceptance/evaluation.md`), and the routed selection SHALL NOT be merged unless the report shows PASS for every threshold. Any FAIL, INVALID, INCOMPLETE or missing threshold means the branch stays unmerged. The evaluation is a merge gate of this change and is not deferred to another epic.

#### Scenario: All thresholds pass
- **WHEN** `acceptance/evaluation.md` records PASS for every threshold and its recorded git head is the head being merged, or no `src/` file changed since it
- **THEN** the merge task may proceed and the pull request description quotes the report

#### Scenario: One threshold fails
- **WHEN** the report records FAIL for the cost threshold
- **THEN** the routed selection is not merged and the branch stays open

#### Scenario: A stale report
- **WHEN** a commit that touches `src/` lands after the head recorded in the report
- **THEN** the report is stale, the merge gate fails, and a new numbered run within the remaining budget is needed

### Requirement: The merge gate is a marked test that runs in CI
A test marked `merge_gate` SHALL assert that `acceptance/evaluation.md` says `MERGE ALLOWED` and that the `src/` tree hash of its recorded head equals HEAD's. The marker is deselected by `addopts`, a dedicated CI step `-m merge_gate` runs it on pull requests, and it SHALL be skipped when the tree holds none of `routing_select.py`, `routing_evidence.py`, `data/routing_evidence.json` and a `0006` migration, whatever the report says.

#### Scenario: Full history
- **WHEN** CI runs the step
- **THEN** the checkout has full history so the recorded head's tree can be read

#### Scenario: Unit tests stay in the suite
- **WHEN** the default suite runs
- **THEN** the parser, generator and skip-logic tests on temporary trees run, and the gate itself does not

#### Scenario: Router present, no report
- **WHEN** the tree holds `routing_select.py` and `acceptance/evaluation.md` does not exist
- **THEN** the `merge_gate` test fails

#### Scenario: The commit hook
- **WHEN** the pre-commit hook runs the default suite
- **THEN** no `merge_gate` test runs

#### Scenario: Media alone
- **WHEN** the routed selection has been unwound (none of the four routing-owned artifacts exists), whether or not a report exists
- **THEN** the test is skipped, its file stays, and CI stays green

#### Scenario: Source changed after the report
- **WHEN** the `src/` tree hash of HEAD differs from the recorded head's
- **THEN** the test fails

### Requirement: The thresholds are written down before any run
The thresholds SHALL be committed in this spec, in `tests/routing_eval/thresholds.py` and in `acceptance/preregistration.md` (with the registering commit) BEFORE any scored run, and SHALL NOT change after a result exists. A change of margin, class mapping, shortlist or evidence after a run SHALL start a new numbered run reported beside every earlier one. The owner may edit thresholds only before registration.

#### Scenario: The registered values
- **WHEN** the thresholds are registered
- **THEN** they are T0 at least 15 main and 5 held-out prompts per kept class, at least half of each subset machine-checkable; T1a decision p95 under 5 ms; T1b 0 added network calls; T2a median added wall time under 50 ms; T2b live latency ratio against the status quo at most 1.10; T2c cold start under 100 ms; T3a `tools/list` at most 59779; T3b `routing` object at most 400 bytes; T3c `input` byte-identical

#### Scenario: The registered quality and cost values
- **WHEN** the thresholds are registered
- **THEN** they are T4a cost at most 0.75 of the strongest arm; T4b at most 4.0 of the cheapest arm; T4c at most 1.00 of the status quo; T5a, T5b and T5d paired non-inferiority with 95 percent lower bounds of -0.10 overall, -0.15 per class and -0.10 against the status quo; T5c Cohen's kappa at least 0.70; T5e strongest minus cheapest at least 0.15

#### Scenario: Registered before the run
- **WHEN** a live arm is started and `acceptance/preregistration.md` is not committed, or the thresholds module differs from it
- **THEN** the harness refuses to run and spends nothing

#### Scenario: A threshold edited after a result
- **WHEN** a threshold value changes after a scored run exists for the same configuration
- **THEN** the offline test that pins the thresholds fails

#### Scenario: Tuning is a new run
- **WHEN** the margin is changed after run 1 fails
- **THEN** run 2 is recorded with its own configuration hash beside run 1, and a PASS counts only for the run whose configuration is the head being merged

### Requirement: The labeled prompt set is fixed, large enough, split and pinned by hash
The set SHALL be `tests/fixtures/routing_prompts.json`, extended in task 3.2: each routed prompt carries its tier label, a `task` label, a `split` (`main` or `heldout`) and an `eval` object (a `check` or a rubric of at most five binary criteria). Its SHA-256 SHALL be committed in `acceptance/prompt_set.sha256` before any live run and a test SHALL fail on a mismatch.

#### Scenario: Class counts
- **WHEN** the offline test reads the set
- **THEN** each class has at least 15 `main` and 5 `heldout` prompts, at least half of each subset has a `check`, and every tier label of the earlier set is unchanged

#### Scenario: The set changed
- **WHEN** a prompt or a `split` value is edited after `acceptance/prompt_set.sha256` was committed
- **THEN** the hash test fails until a new run is registered

#### Scenario: A checkable answer
- **WHEN** a prompt has a `number` check with tolerance 0.5 and the answer says 41.7 where the label is 42
- **THEN** the harness scores the prompt 1 and executes no code from the answer

#### Scenario: Answers do not drift
- **WHEN** a browsing prompt is authored
- **THEN** its answer is a dated fact or a rubric that names no changing value

#### Scenario: The split is frozen early
- **WHEN** task 3.1 has labeled the tasks
- **THEN** the `split` values are assigned and their hash recorded before the router exists, and no later commit changes them

### Requirement: The routing decision is cheap and adds no network call
The harness SHALL time `routing.resolve` plus `routing_select.select` offline over every prompt under three evidence states (shipped empty, verified, worst-case synthetic), and T1a passes only when p95 is under 5 ms in each. T1b passes only when a routed ask makes the same number of upstream requests as the ask naming the chosen model, none of them a models listing.

#### Scenario: Timing
- **WHEN** the microbenchmark runs at least 200 repetitions per prompt after 20 discarded warm-up calls in each evidence state
- **THEN** the report holds p50, p95 and p99 per state, the Python version and the machine, and T1a is PASS only for a p95 under 5 in every state

#### Scenario: Request count
- **WHEN** a routed ask runs against a counting stub
- **THEN** exactly one upstream request is made, none of it a models listing, and T1b is PASS

#### Scenario: A mutation
- **WHEN** the selector is changed to fetch the catalog on each call
- **THEN** the request-count test goes red

#### Scenario: The worst case
- **WHEN** the synthetic file is built
- **THEN** it shortlists every baseline model, scores each on every benchmark and puts all within the margin, so the contender set is as large as possible

### Requirement: A routed call adds little wall time against naming the model
T2a SHALL pass when, over at least 200 interleaved pairs against the same instant stub upstream in each evidence state, the median added time of a routed ask over the same prompt with `model` set to the model the routed call chose is under 50 ms; T2c when the first routed call of a fresh process takes under 100 ms; T2b when the live routed arm's median latency is at most 1.10 times the status-quo arm's.

#### Scenario: Paired overhead
- **WHEN** the paired run completes after a warm-up
- **THEN** the report holds the median, p95 and pair count per evidence state, and T2a is PASS only for a median under 50 ms in each

#### Scenario: Cold start
- **WHEN** a fresh process serves its first routed ask
- **THEN** the time is recorded and T2c is PASS only under 100 ms

#### Scenario: Decisions classifier reported apart
- **WHEN** the classifier is `decisions`
- **THEN** its added time is a separate line, it stays opt-in, and it does not count toward T2a

### Requirement: A routed call adds no tokens and little response size
T3c SHALL pass only when the routed upstream request's `input` is byte-identical to the request for the same prompt with `model` set to the chosen model, the only difference being the optional `reasoning.effort` key. T3b SHALL pass when the largest serialized `routing` object of the run is at most 400 bytes. T3a SHALL pass when each of the three measured servers' `tools/list` is at most 59779 bytes.

#### Scenario: Identical input
- **WHEN** the same prompt is asked routed and with the chosen model named
- **THEN** the two `input` values are byte-identical and no `instructions` text was added

#### Scenario: Routing object size
- **WHEN** the largest `routing` object of the run is serialized, a `model_retired:` reason included
- **THEN** it is at most 400 bytes and the report records the byte count

#### Scenario: Tools list
- **WHEN** the default, dynamic and dynamic-with-Decisions servers are measured
- **THEN** each is at most 59779 bytes

### Requirement: Four arms are measured with the same request shape
The live run SHALL send every prompt through four arms of one request shape, each under its own `project`: routed, strongest (the named model `anthropic/claude-opus-5-5`), cheapest (lowest blended price among available shortlist models, ties to the smaller id) and status quo (`perplexity/sonar`, the default route at commit d2798cd, explicit shape, no `reasoning`). Strongest and cheapest SHALL get the effort D5 gives for the prompt's tier, clipped to their accepted levels or none.

#### Scenario: Recorded per request
- **WHEN** a request is sent
- **THEN** a recording transport in the harness stores its cost, tokens, cached tokens, search calls, effort and latency

#### Scenario: Strongest is a named model
- **WHEN** the evidence is edited so another model scores highest
- **THEN** the strongest arm still runs `anthropic/claude-opus-5-5`

#### Scenario: Status quo is pinned
- **WHEN** the default route's model changes in a later release
- **THEN** the status-quo arm still runs the model registered at pre-registration

#### Scenario: Arms are separated
- **WHEN** the run ends
- **THEN** `perplexity_usage` can be filtered to each arm by its project, and the record holds the per-arm search-call, cached-token and output-token counts

#### Scenario: Interleaved
- **WHEN** a prompt is sent
- **THEN** its four requests run in an order varied by a fixed seed, so no arm always runs first

### Requirement: Spend is measured against three baselines
Spend SHALL be the sum of recorded `cost_usd` per arm. T4a passes when routed spend is at most 0.75 times the strongest arm's, T4b when it is at most 4.0 times the cheapest arm's, T4c when it is at most 1.00 times the status quo's. A request with unknown cost SHALL be re-sent once from the reserve; an arm whose request is still unknown is INVALID, not the whole run.

#### Scenario: Cost saved against the strongest model
- **WHEN** the strongest arm costs 1.00 USD and the routed arm 0.70
- **THEN** T4a is PASS, and with 0.80 it is FAIL

#### Scenario: Not dearer than today
- **WHEN** the status quo costs 0.30 USD and the routed arm 0.35
- **THEN** T4c is FAIL

#### Scenario: Not just the cheapest model
- **WHEN** the cheapest arm costs 0.10 USD and the routed arm 0.45
- **THEN** T4b is FAIL

#### Scenario: Unknown cost re-run
- **WHEN** one event has cost source `none`
- **THEN** that prompt is re-sent once from the reserve, and only a second unknown makes that arm INVALID

### Requirement: Quality is a paired non-inferiority test
A prompt's quality SHALL be 1 or 0 for a `check` and the fraction of rubric criteria met for a rubric. T5a SHALL pass when the one-sided 95 percent lower bound of the paired mean difference routed minus strongest is at least -0.10 overall, T5b when it is at least -0.15 in each class, and T5d when routed minus status quo is at least -0.10 overall, each from a paired bootstrap of prompts (10000 resamples, fixed seed, stratified by class).

#### Scenario: Within the margin
- **WHEN** the paired routed-minus-strongest mean is -0.02 with a 95 percent lower bound of -0.07
- **THEN** T5a is PASS, and with a lower bound of -0.12 it is FAIL

#### Scenario: One class lags
- **WHEN** the lower bound in `coding` is -0.18
- **THEN** T5b is FAIL although the overall bound passes

#### Scenario: Worse than today
- **WHEN** the lower bound of routed minus status quo is -0.14
- **THEN** T5d is FAIL

### Requirement: The judge is blind to labels and validated against the checks
Rubric criteria and the judge validation SHALL be judged by `perplexity_decide` `choice` questions with arm labels removed, answers shuffled by a fixed seed and the check label and expected value never shown, by one recorded judge model. T5c passes when Cohen's kappa between the judge and the machine check on the checkable half is at least 0.70, and the report SHALL give the judge's score per arm.

#### Scenario: The judge never sees the label
- **WHEN** a checkable answer is sent to the judge
- **THEN** the question holds the prompt and the answer, and neither the expected value nor the check kind

#### Scenario: An unreliable judge
- **WHEN** kappa is 0.55
- **THEN** T5c is FAIL and no rubric score is used to pass anything

#### Scenario: A biased arm
- **WHEN** the judge scores the routed arm 0.15 above its check score
- **THEN** the report flags that arm

### Requirement: The set must discriminate between a strong and a cheap model
T5e SHALL require the strongest arm's overall quality to exceed the cheapest arm's by at least 0.15; otherwise the run is INVALID (a set that cannot tell the models apart cannot show parity).

#### Scenario: A flat set
- **WHEN** the strongest arm scores 0.80 and the cheapest 0.72
- **THEN** the run is INVALID and no quality threshold is used

### Requirement: A later run is confirmed on the held-out subset
The first numbered run SHALL score the `main` subset only. Any later run (a change of margin, mapping, shortlist or evidence, or a rerun after a `src/` fix) SHALL also score the `heldout` subset, and its PASS SHALL require each held-out paired difference (routed minus strongest, routed minus status quo) to be no worse than minus the registered margin and the cost thresholds to hold on it.

#### Scenario: First run
- **WHEN** run 1 is scored
- **THEN** no `heldout` prompt is sent

#### Scenario: Tuned run
- **WHEN** run 2 follows a margin change or a `src/` fix
- **THEN** the held-out subset is scored and a held-out shortfall makes the verdict DO NOT MERGE

### Requirement: Live spend is budgeted, piloted and bounded
All live work of the branch SHALL together stay under 10 USD, with the evaluation caps summing below it. A 6-prompt PILOT, run from a throwaway script outside the repo on prompts outside the labeled set, SHALL estimate cost per arm and the paired variance only and project one `main` run, one held-out run and one routed re-run. Registration SHALL state the false-fail probability and pick n so it is at most 10 percent within the budget.

#### Scenario: Output bound
- **WHEN** the harness runs
- **THEN** it sets `max_output_tokens` and stops before a request whose upper bound would exceed its cap

#### Scenario: The caps come from the pilot
- **WHEN** the caps are registered
- **THEN** they start from pilot 0.80, strongest 4.00, routed 1.20, status quo 0.60, cheapest 0.30, judge 0.10 and reserve 1.20 (sum 8.20), the pilot's projection may change them, the other live work is itemised at 1.30, and the total stays below 10.00

#### Scenario: The caps come from the pilot
- **WHEN** the caps are registered
- **THEN** they start from pilot 0.80, strongest 4.00, routed 1.20, status quo 0.60, cheapest 0.30, judge 0.10 and reserve 1.20 (sum 8.20), the pilot's projection may change them, the other live work is itemised at 1.30, and the total stays below 10.00

#### Scenario: The pilot says it does not fit
- **WHEN** the pilot projects the strongest arm above its cap
- **THEN** the harness stops before registration and the owner decides (a larger cap, up to the owner's standing cap, or the minimum set)

#### Scenario: Registration states n
- **WHEN** the pilot's variance gives an n above what the budget supports
- **THEN** registration records that and stops for the owner

#### Scenario: A cap is reached
- **WHEN** an arm's next request could exceed its cap
- **THEN** the run is INCOMPLETE and every threshold needing that arm is INCOMPLETE

#### Scenario: Reusing arm results
- **WHEN** a later run keeps the strongest, cheapest and status-quo request bodies unchanged
- **THEN** their recorded answers are reused by request-body hash, and the routed arm is reused only for prompts whose chosen model and effort are unchanged

#### Scenario: The upper bound
- **WHEN** the harness decides whether to send a request
- **THEN** the bound is the larger of 1.5 times the pilot's largest cost for that arm and the cost of `max_output_tokens` plus 50000 input tokens at the model's prices

### Requirement: An evaluation with no verified evidence is invalid, never a pass
The shipped evidence has empty scores, so the router always falls back and cannot beat the baseline. A failed coverage gate of `routing-evidence` makes the run INVALID with no request, and the harness SHALL refuse to score unless the router, not the fallback, chooses for at least 75 percent of EACH class. If, with verified evidence, T4a, T4b, T4c, T5a, T5b or T5d FAIL, the outcome SHALL be DO NOT MERGE the routed selection.

#### Scenario: Coverage gate failed
- **WHEN** `acceptance/coverage.md` records `evidence too thin: router cannot be evaluated`
- **THEN** the run is INVALID, no live request is sent, and the owner decides before any spend

#### Scenario: The shipped state
- **WHEN** the harness starts against the packaged evidence with empty scores
- **THEN** it reports INVALID because the router would only measure the fallback, and no live request is sent

#### Scenario: One class falls back
- **WHEN** the router chooses for 90 percent of `coding` and `reasoning` but 60 percent of `browsing`
- **THEN** the run is INVALID and the report names the class

#### Scenario: Sourced evidence, failed stick
- **WHEN** the evidence is verified and the cost threshold FAILs
- **THEN** the report's verdict is DO NOT MERGE and the branch stays unmerged

### Requirement: The report states one verdict line per threshold and reconciles its costs
`acceptance/evaluation.md` SHALL be generated by the harness and hold, per run, the git head, the SHA-256 of the prompt set, thresholds and evidence, the models of the four arms, spend per arm, one line `T4a PASS|FAIL|INVALID|INCOMPLETE: <measured> against <threshold>` per threshold and a final verdict `MERGE ALLOWED` or `DO NOT MERGE`. Spend SHALL be reconciled to the nano-USD against the harness's own client-side sums of the responses, not only against `perplexity_usage`.

#### Scenario: Verdict lines
- **WHEN** the report is generated
- **THEN** it has a line for each of T0, T1a, T1b, T2a, T2b, T2c, T3a, T3b, T3c, T4a, T4b, T4c, T5a, T5b, T5c, T5d and T5e, and the verdict is `MERGE ALLOWED` only when every line is PASS

#### Scenario: Two sums agree
- **WHEN** the client-side sum and the `perplexity_usage` total of a run differ by one nano-USD
- **THEN** the run is flagged unreconciled and not accepted

#### Scenario: Quoted in the pull request
- **WHEN** the pull request is opened
- **THEN** its description quotes those lines and the verdict

### Requirement: No savings or quality claim is made before the report passes
No document, help text, tool description, README, CHANGELOG or pull request SHALL state a savings, speed or quality figure for routing before the report records `MERGE ALLOWED`; after it does, a document MAY quote the measured figures with the report as its source and the run's date.

#### Scenario: Before the report
- **WHEN** the documentation task runs and the report has any FAIL, INVALID or INCOMPLETE
- **THEN** no document quotes a savings figure

#### Scenario: After a pass
- **WHEN** the report records `MERGE ALLOWED`
- **THEN** the README may quote the measured percentages and names `acceptance/evaluation.md` as the source

### Requirement: The code is frozen before the evaluation
`src/` SHALL be frozen, with Gate 2 over the code recorded, before pre-registration, so the report stays valid; documentation and the harness under `tests/routing_eval/` follow, and a docs-and-harness review replaces the final review. Any `src/` commit after the report SHALL require a new numbered run within the remaining budget.

#### Scenario: Order
- **WHEN** the tasks run
- **THEN** the code Gate 2 and the offline unwind rehearsal precede task 7.2, and documentation follows the report

#### Scenario: A late fix
- **WHEN** a `src/` fix lands after the report
- **THEN** the merge gate test fails until a new numbered run records the new head

### Requirement: A failed evaluation leaves media-inputs mergeable alone, and publishing needs the owner
When the verdict is not `MERGE ALLOWED`, the routed selection, its evidence file and migration `0006` SHALL NOT be merged and `media-inputs` SHALL remain mergeable alone (it takes nothing from `0006`). Its matrix and the existing dynamic mode stay unpublished under the owner's hold of 2026-10-29, so task 7.7 SHALL record that an owner decision is required before any tag.

#### Scenario: Migration 0006 is not needed
- **WHEN** `media-inputs` ships without `routing-v2`
- **THEN** the revision head is `0005` and no media code reads `chat_messages.tier`, `chat_messages.routed_model`

#### Scenario: The gate without the router
- **WHEN** `media-inputs` ships without `routing-v2`
- **THEN** the attachment gate checks the final route of the existing resolve (explicit model, pin, tier model, default, or a preset) and no router substitution or held-model rule exists

#### Scenario: Nothing is tagged by default
- **WHEN** the verdict is `DO NOT MERGE`
- **THEN** task 7.7 records "owner decision required before any tag; default: nothing published"

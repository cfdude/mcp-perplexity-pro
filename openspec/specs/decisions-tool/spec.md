# decisions-tool Specification

## Purpose
Defines `perplexity_decide`, the tool that asks the Decisions API to rate a piece of text: its arguments and local validation, the request it builds, the answer shape, what a request costs, and that every request is recorded as spend.

## Requirements

### Requirement: Decide tool
The server SHALL provide `perplexity_decide`, a synchronous stateless tool that puts one to 32 typed questions about a `state` to the Decisions API and returns an answer per question. It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` false and `openWorldHint` true, and its description SHALL state the cost, that answers are model probabilities, the question types and that images are unsupported.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_decide` is present with typed parameters, an output schema, the cost, the probabilities wording and the question-type wording in its description

#### Scenario: Result validates
- **WHEN** a decision succeeds
- **THEN** its structured content validates against the advertised output schema and its text content lists one line per question

### Requirement: State
`state` SHALL be non-blank text, or a non-empty JSON object or list, whose serialized form is at most 200000 characters (this server's own cap; the API's limit is 262144 tokens). A blank or empty state, an oversized one, or one holding image content (an `image_url` key anywhere, or a string starting `data:image/`) SHALL fail with `invalid_request` naming `state` before any upstream call, project creation or usage event. The API accepts and bills an empty state.

#### Scenario: Blank state
- **WHEN** a client passes `state` `"   "`, `""`, `{}` or `[]`
- **THEN** each call fails with `invalid_request` naming `state`, nothing is sent and no event or project is created

#### Scenario: Image refused
- **WHEN** a client passes a state list holding an `image_url` part
- **THEN** the call fails with `invalid_request` naming `state` and saying images are not supported

#### Scenario: Text and structure sent
- **WHEN** a client passes a string state, and separately an object state
- **THEN** each request carries that state unchanged

### Requirement: Questions
`questions` SHALL be a non-empty mapping of at most 32 entries (this server's own cap; the API allows 128), each name a non-blank string of at most 128 characters and each value a question with a `type` of `noul`, `choice` or `score`. Any other shape, count or type SHALL fail with `invalid_request` naming `questions` before any call. Unknown keys inside a question are refused.

#### Scenario: Count and names
- **WHEN** a client passes no questions, 33 questions, or a question named `"  "`
- **THEN** each call fails with `invalid_request` naming `questions` and nothing is sent

#### Scenario: Unknown type
- **WHEN** a client passes a question of type `rank`
- **THEN** the call fails with `invalid_request` naming the question and nothing is sent

#### Scenario: Thirty-two accepted
- **WHEN** a client passes 32 questions
- **THEN** the request carries all 32

### Requirement: Question shapes
A `noul` question SHALL have `criteria` (an object whose keys are `true` and `false`) or `instructions`. A `choice` question SHALL have `criteria`, an object of 1 to 255 options (an option's description may be null). A `score` question SHALL have `criteria`, a list of 1 to 10 levels. `instructions`, when given, SHALL be text, an object or a list. Each violation SHALL fail with `invalid_request` naming the question before any call.

#### Scenario: Noul criteria keys
- **WHEN** a noul question's criteria has a key other than `true` and `false`
- **THEN** the call fails with `invalid_request` naming that question

#### Scenario: Noul without a rule
- **WHEN** a noul question has neither criteria nor instructions
- **THEN** the call fails with `invalid_request` naming that question

#### Scenario: Choice options
- **WHEN** a choice question has empty criteria, or its criteria is a list
- **THEN** each call fails with `invalid_request` naming that question

#### Scenario: Score levels
- **WHEN** a score question has 11 levels, or none
- **THEN** each call fails with `invalid_request` naming that question

#### Scenario: Recorded shapes
- **WHEN** the options of the seven recorded requests the tool accepts (`decisions_noul`, `decisions_choice`, `decisions_score`, `decisions_three_questions`, `decisions_model_v1`, `decisions_11_questions`, `decisions_32_questions`) are passed to the tool
- **THEN** the request equals that recorded request

### Requirement: Model
`model` SHALL be `pplx-decider-v1.1-27b` (the default) or `pplx-decider-v1-27b` and the request SHALL always name it. Any other value SHALL fail with `invalid_request` naming `model` before any call.

#### Scenario: Default model
- **WHEN** a client passes no `model`
- **THEN** the request carries `pplx-decider-v1.1-27b`

#### Scenario: Older model and unknown model
- **WHEN** a client passes `pplx-decider-v1-27b`, and separately `pplx-decider-nope`
- **THEN** the first request carries it and the second call fails with `invalid_request` naming `model`

### Requirement: Project
`project` SHALL default to `default`, be validated by the existing project-name rules before any call, and name the project the event is recorded under. An invalid name SHALL fail with `invalid_request` before any request, project or event.

#### Scenario: Default and invalid project
- **WHEN** a client passes no `project`, and separately `../x`
- **THEN** the first result and event carry `default` and the second call fails with `invalid_request` with no request, project or event

### Requirement: Request carries only what was asked
The request SHALL hold `model`, `state`, `questions` and nothing else; no field is invented and no unknown field is sent (the API refuses an unknown field with a generic 400).

#### Scenario: Minimal request
- **WHEN** a client asks one noul question with instructions about a text state
- **THEN** the request body holds exactly `model`, `state` and `questions`

### Requirement: Answers
The result SHALL hold `answers`, a mapping from each question name the caller gave, in the caller's order, to its answer: for `noul` the probability; for `choice` the chosen option, `confidence` and every option's probability; for `score` the `score`, `confidence`, `legend` and `probabilities`. Fields that do not apply are null. It SHALL also hold `model`, `input_tokens`, `output_tokens`, `cost_usd`, `cost_source`, `latency_ms`, `project` and `warnings`.

#### Scenario: Three answers
- **WHEN** the API returns the recorded three-question response
- **THEN** the result holds a noul probability, a choice with three probabilities and a score with a four-entry legend, under the caller's names, with 347 input tokens and 3 output tokens

### Requirement: Unreadable answers do not fail the call
A question with no readable answer (missing, not an object, an unknown type) SHALL be left out of `answers` with one warning naming it, and a non-numeric or non-finite number SHALL become null; the call SHALL NOT fail, because the request was billed.

#### Scenario: Missing answer
- **WHEN** a response lacks the answer for one question
- **THEN** that name is absent from `answers`, a warning names it, and the other answers are returned

#### Scenario: Odd answer values
- **WHEN** an answer carries a non-numeric probability
- **THEN** that field is null and the call does not fail

### Requirement: Option text is scrubbed
Strings in an answer (the chosen option, legend text, probability keys) come from the caller's own criteria; the configured API key SHALL be replaced by `[redacted]` in them and they SHALL be cut to 500 characters. A `pplx-` shaped example and a documented model id inside them are kept.

#### Scenario: Key in an option name
- **WHEN** a response's chosen option contains the configured key beside `pplx-decider-v1.1-27b`
- **THEN** the returned option holds `[redacted]` for the key and the model id as received

### Requirement: Cost of a decision
The cost of a request SHALL be its input tokens at the documented price ($0.02 per million; output tokens are free; no per-request fee), whatever the question count and model, with source `computed`. When `input_tokens` is missing or not a non-negative whole number the cost SHALL be unknown (`cost_usd` null, source `none`), never zero. The result carries `cost_usd` as an exact decimal string.

#### Scenario: Recorded request
- **WHEN** the recorded three-question response (347 input tokens) is returned
- **THEN** the result has `cost_usd` `"0.00000694"` and `cost_source` `computed`

#### Scenario: Unreadable usage
- **WHEN** a response carries no `usage`, or an `input_tokens` that is a boolean, negative, a float or a string
- **THEN** the call succeeds with `cost_usd` null and `cost_source` `none`, and the event has cost 0 and source `none`

#### Scenario: Output tokens missing
- **WHEN** `usage` holds a valid `input_tokens` and no `output_tokens`
- **THEN** the cost is computed from the input tokens, `output_tokens` is null and the call does not fail

### Requirement: Decide is recorded
Each decision that reaches the API SHALL be recorded once as a usage event: tool `perplexity_decide`, API family `decisions`, the response `model`, no preset, no request id (the body has none), the project name, the measured latency, the token counts, and the computed cost. A failed request carries its error category with cost 0 and source `none`; a 200 that cannot be read is `unexpected_response`. Identical repeated requests each record an event.

#### Scenario: Successful decision
- **WHEN** a decision completes with the recorded response
- **THEN** exactly one event exists with status `ok`, API family `decisions`, tool `perplexity_decide`, model `pplx-decider-v1.1-27b`, 347 input tokens, 3 output tokens, no request id, cost 6940 nano-USD and source `computed`

#### Scenario: Failed decision
- **WHEN** the API returns the recorded 401, and separately 503
- **THEN** each leaves one event with that error category, cost 0 and source `none`

#### Scenario: Local refusal
- **WHEN** a call is refused by local validation
- **THEN** no event and no project is created and nothing is sent

### Requirement: Recording order and privacy
The tool SHALL resolve and commit its project before the upstream call, hold no write unit across the call, record the event after it, and never store or log the state, the questions or the answers.

#### Scenario: No content stored
- **WHEN** a decision is made with a distinctive state and question text
- **THEN** no `usage_events` column and no log record contains that text

#### Scenario: Project survives failure
- **WHEN** a decision for a new project fails upstream
- **THEN** the project exists and one failure event is recorded

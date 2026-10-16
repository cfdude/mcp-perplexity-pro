# Spec Delta

## Purpose
Defines how dynamic routing asks Perplexity's Decisions API to pick a tier for a prompt, how it is bounded, recorded and replaced by the rules classifier when it fails.

## ADDED Requirements

### Requirement: One choice question picks the tier
The Decisions classifier SHALL send one request to the Decisions API with the default decider model, a state holding the prompt text (its first 4000 characters) and one `choice` question named `tier` whose options are `light`, `standard` and `complex`, each with a fixed one-line criterion. The answer's `choice` is the tier.

#### Scenario: The request
- **WHEN** a prompt of 6000 characters is classified by the Decisions classifier
- **THEN** one request is sent whose state holds the first 4000 characters, whose questions hold exactly the `tier` choice with the three options, and whose model is the default decider model

#### Scenario: The answer
- **WHEN** the response answers `tier` with choice `complex`
- **THEN** the tier is `complex`

### Requirement: A weak answer is not trusted alone
When the answer's confidence is below 0.5 the classifier SHALL also compute the rules' tier for the same text and use the higher of the two, with a reason saying so. A confidence of 0.5 or more, or an answer with no readable confidence and a known choice, SHALL use the answer's tier alone.

#### Scenario: Low confidence
- **WHEN** the answer is `light` with confidence 0.4 and the rules say `complex`
- **THEN** the tier is `complex` and the reason says the answer was weak and the rules' tier was higher

#### Scenario: Confident answer
- **WHEN** the answer is `light` with confidence 0.9 and the rules say `complex`
- **THEN** the tier is `light`

### Requirement: Classification is bounded and never fatal
The whole classification, retries included, SHALL end within 3 seconds. Any failure (a timeout, any error category, an answer that is unreadable or whose choice is not one of the three tiers) SHALL fall back to the rules' tier, with a reason naming the failure category, and SHALL NOT fail or delay the call beyond the bound.

#### Scenario: Timeout
- **WHEN** the Decisions request does not answer within 3 seconds
- **THEN** the call proceeds with the rules' tier and the reason says the classifier timed out

#### Scenario: Rate limited
- **WHEN** the Decisions API answers `rate_limited`
- **THEN** the call proceeds with the rules' tier and the reason names `rate_limited`

#### Scenario: Unknown choice
- **WHEN** the answer's choice is `huge`
- **THEN** the call proceeds with the rules' tier and the reason says the answer was unreadable

### Requirement: Each Decisions request is recorded
Each Decisions request the classifier makes, answered or failed, SHALL be recorded as one usage event with API family `decisions`, the name of the tool whose call caused it, that call's project, and the cost computed from the input tokens as `perplexity_decide` is. The ask or chat call's own event is unchanged.

#### Scenario: Two events
- **WHEN** one `perplexity_ask` call in dynamic mode with the Decisions classifier completes
- **THEN** two usage events exist for it: one with API `agent` and one with API `decisions`, both with tool `perplexity_ask`

#### Scenario: A failed classification is recorded
- **WHEN** the Decisions request fails with `rate_limited`
- **THEN** one `decisions` event exists with status `rate_limited` and the ask is still answered

### Requirement: The classifier runs only when it is needed
The classifier SHALL run only for a call in dynamic mode with the Decisions classifier that names no `depth`, `tier` or `model`, whose `search` is not false and whose other options validated. It SHALL run after the validation that precedes any billed request, so an invalid call makes no Decisions request. A chat follow-up still never routes below the tier its chat last used.

#### Scenario: Explicit selector
- **WHEN** a call in this mode names `depth` `fast`
- **THEN** no Decisions request is made

#### Scenario: Invalid call
- **WHEN** a call in this mode has an invalid option
- **THEN** it fails as it does today and no Decisions request is made

#### Scenario: Search off
- **WHEN** a call in this mode has `search` false
- **THEN** no Decisions request is made and the standard tier's model runs

#### Scenario: Follow-up floor
- **WHEN** the chat's last turn ran `complex` and the Decisions classifier answers `light` for the follow-up
- **THEN** the follow-up runs the `complex` tier

### Requirement: The prompt is not repeated outside the request
The prompt text SHALL appear in the Decisions request and nowhere else the classifier writes: not in the routing reason, the logs or the recorded usage event.

#### Scenario: A secret-shaped prompt
- **WHEN** a prompt containing `hunter2` is classified
- **THEN** the reason, the log records and the usage event do not contain `hunter2`

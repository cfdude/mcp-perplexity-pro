# Spec Delta

## Purpose
Defines how dynamic routing asks Perplexity's Decisions API to pick a tier for a prompt, how it is bounded, recorded and replaced by the rules classifier when it fails.

## ADDED Requirements

### Requirement: One choice question picks the tier
The Decisions classifier SHALL send one request to the Decisions API with the default decider model, a state that is the prompt text as a string (its first 4000 characters) and one `choice` question named `tier` whose options are `light`, `standard` and `complex`, each with a fixed one-line criterion. The answer's `choice` is the tier.

#### Scenario: The request
- **WHEN** a prompt of 6000 characters is classified by the Decisions classifier
- **THEN** one request is sent whose state holds the first 4000 characters, whose questions hold exactly the `tier` choice with the three options, and whose model is the default decider model

#### Scenario: The answer
- **WHEN** the response answers `tier` with choice `complex`
- **THEN** the tier is `complex`

### Requirement: A weak answer is not trusted alone
The answer's strength is the probability it gives the chosen option, or its `confidence` when no probabilities are readable. Below 0.5 the classifier SHALL also compute the rules' tier for the same text and use the higher of the two, ties going to the Decisions tier. At 0.5 or more, or with no readable strength and a known choice, it SHALL use the answer's tier alone.

#### Scenario: Weak answer
- **WHEN** the chosen option's probability is 0.4 and the rules say a higher tier
- **THEN** the tier is the rules' tier and the reason says the answer was weak

#### Scenario: Weak answer, same tier
- **WHEN** the chosen option's probability is 0.4 and the rules say the same tier
- **THEN** the tier is that tier and the classifier is `decisions`

#### Scenario: Confident answer
- **WHEN** the chosen option's probability is 0.9 and the rules say a higher tier
- **THEN** the tier is the Decisions tier

#### Scenario: Exactly 0.5
- **WHEN** the chosen option's probability is exactly 0.5
- **THEN** the answer is trusted alone

### Requirement: Classification is bounded and never fatal
The Decisions request SHALL be made once, with no retry, and end within 3 seconds, so a rate limit is reported as such at once. Any failure (a timeout, any error category, an answer that is unreadable or whose choice is not one of the three tiers) SHALL fall back to the rules' tier, with a reason naming the failure category, and SHALL NOT fail the call or wait on the request beyond the bound.

#### Scenario: Timeout
- **WHEN** the Decisions request does not answer within 3 seconds
- **THEN** the call proceeds with the rules' tier, the reason names `network_timeout`, and one `decisions` event is recorded with status `network_timeout`

#### Scenario: Rate limited
- **WHEN** the Decisions API answers `rate_limited`, even with a `Retry-After`
- **THEN** the call proceeds at once with the rules' tier, the reason names `rate_limited` and one `decisions` event is recorded with that status

#### Scenario: Unknown choice
- **WHEN** the answer's choice is `huge`
- **THEN** the call proceeds with the rules' tier and the reason says the answer was unreadable, with no failure category

### Requirement: Each Decisions request is recorded
Each Decisions request the classifier makes, answered, failed or timed out, SHALL be recorded as one usage event with API family `decisions`, the name of the tool whose call caused it, that call's project, and the cost computed from the input tokens as `perplexity_decide` is. The ask or chat call's own event is unchanged.

#### Scenario: Two events
- **WHEN** one `perplexity_ask` call in dynamic mode with the Decisions classifier completes
- **THEN** two usage events exist for it: one with API `agent` and one with API `decisions`, both with tool `perplexity_ask`

#### Scenario: A failed classification is recorded
- **WHEN** the Decisions request fails with `rate_limited`
- **THEN** one `decisions` event exists with status `rate_limited` and the ask is still answered

### Requirement: The classifier runs only when it is needed
The classifier SHALL run only for a call in dynamic mode with the Decisions classifier that names no `depth`, `tier` or `model`, whose `search` is not false and whose options and project name validated. An invalid call makes no Decisions request.

#### Scenario: Explicit selector
- **WHEN** a call in this mode names `depth` `fast`
- **THEN** no Decisions request is made

#### Scenario: Invalid call
- **WHEN** a call in this mode has an invalid option
- **THEN** it fails as it does today and no Decisions request is made

#### Scenario: Search off
- **WHEN** a call in this mode has `search` false
- **THEN** no Decisions request is made and the standard tier's model runs

#### Scenario: Unknown chat
- **WHEN** a nameless follow-up names a chat that does not exist, or one with no stored response and `replay` false
- **THEN** it fails as it does today and no Decisions request is made

#### Scenario: Floor already complex
- **WHEN** the chat's last turn ran `complex` and the follow-up names nothing
- **THEN** no Decisions request is made and the follow-up runs `complex`

#### Scenario: Follow-up floor
- **WHEN** the chat's last turn ran `standard` and the Decisions classifier answers `light` for the follow-up
- **THEN** the follow-up runs the `standard` tier

### Requirement: The prompt is not repeated outside the request
The prompt text SHALL appear in the Decisions request and nowhere else the classifier writes: not in the routing reason, the logs or the recorded usage event.

#### Scenario: A secret-shaped prompt
- **WHEN** a prompt containing `hunter2` is classified
- **THEN** the reason, the log records and the usage event do not contain `hunter2`

### Requirement: Reasons and the classifier field have a closed vocabulary
The routing `reason` of a Decisions-classified call SHALL be at most 120 ASCII characters (the cap `resolve()` enforces on the final reason) built from constants, the tier, a probability and a failure category, never prompt text.

#### Scenario: Reason length
- **WHEN** a Decisions request fails and the rules' own reason is long
- **THEN** the combined reason is at most 120 ASCII characters

### Requirement: The classifier field says who supplied the tier
The routing `classifier` SHALL be `decisions` when the Decisions tier was used (confident, or weak and not lower than the rules' tier) and `rules` when the rules supplied the tier (a failure, or weak and lower). A held follow-up floor does not change it, and a `search` false call, where nothing is classified, has `classifier` null.

#### Scenario: Decisions decided
- **WHEN** the answer is `complex` with probability 0.91
- **THEN** the routing has `classifier` `decisions` and a reason naming `complex` and the probability

#### Scenario: Rules supplied the tier
- **WHEN** the Decisions request fails with `rate_limited`
- **THEN** the routing has `classifier` `rules` and a reason naming `rate_limited` and the rules' own reason, within 120 characters

#### Scenario: Floor held over a Decisions answer
- **WHEN** a follow-up's Decisions answer is `light` and the chat last ran `standard`
- **THEN** the tier is `standard`, `classifier` is `decisions` and the reason says the tier was held

### Requirement: The request carries what the validators accept
The classifier SHALL build its request with the same request builder `perplexity_decide` uses, so the question and state limits apply, and a prompt that the builder refuses (for example one that is an image data URL) SHALL fall back to the rules with a reason saying the prompt was not classifiable.

#### Scenario: A refused prompt
- **WHEN** the prompt starts with `data:image/`
- **THEN** no Decisions request is made and the rules classify with a reason saying the prompt was not classifiable

### Requirement: A chat follow-up is classified only when it can matter
For a chat follow-up the classifier SHALL run after the chat was found with a response to continue (or with `replay` true), and only when the follow-up's floor is below `complex`. A follow-up never routes below the tier its chat last used.

#### Scenario: Floor repeated for a follow-up
- **WHEN** a nameless follow-up's chat last ran `standard`
- **THEN** the classifier runs after the chat lookup and the tier is at least `standard`

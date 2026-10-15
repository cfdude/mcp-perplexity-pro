# Spec Delta

## Purpose
Defines the offline rules classifier that picks a tier (light, standard or complex) for a prompt, so dynamic routing can choose a model without a network call, and the labeled prompt set that pins its behavior.

## ADDED Requirements

### Requirement: The classifier is offline and deterministic
Classifying a text SHALL need no network, no database and no API key, SHALL cost nothing, SHALL record no usage event, and SHALL return the same result for the same text every time.

#### Scenario: Same text, same result
- **WHEN** the same text is classified twice, in one process or two
- **THEN** both results are equal

#### Scenario: No side effects
- **WHEN** a text is classified during a call to `perplexity_ask` in dynamic mode
- **THEN** the only upstream request is the ask itself and the only usage event is the ask's

### Requirement: A result is a tier, a confidence and a reason
A classification SHALL return a tier (`light`, `standard` or `complex`), a confidence (`high` or `low`) and a reason of at most 120 ASCII characters that names the signals that decided it. The reason SHALL NOT contain any text taken from the prompt, because prompts can hold secrets and the reason is returned to the caller and may be logged.

#### Scenario: The reason names signals, not words
- **WHEN** a prompt containing the string `hunter2` is classified
- **THEN** the reason does not contain `hunter2` and names only signals such as length, question count or vocabulary class

### Requirement: Complexity signals raise the tier
A text SHALL classify as `complex` when any one of these holds: it contains at least two distinct words or phrases from the analysis vocabulary (such as compare, evaluate, trade-offs, pros and cons, step by step, root cause, architecture, in depth); it is at least 1200 characters long; it asks three or more distinct questions or lists three or more numbered items. The confidence is `high` when two or more of these hold, otherwise `low`.

#### Scenario: Two analysis words
- **WHEN** the text asks to compare two libraries and evaluate their trade-offs
- **THEN** the tier is `complex`

#### Scenario: A long text
- **WHEN** a text of 1500 characters with no analysis vocabulary is classified
- **THEN** the tier is `complex` with confidence `low`

#### Scenario: Several questions
- **WHEN** a text holds three separate questions
- **THEN** the tier is `complex`

### Requirement: Short lookups are light
A text SHALL classify as `light` when it is at most 120 characters, holds one question, opens in a lookup form (such as what is, who is, when did, where is, how many, define, latest, current price) and triggers no complexity signal. The confidence is `high`.

#### Scenario: A lookup
- **WHEN** the text is `What is the latest stable Python release?`
- **THEN** the tier is `light` with confidence `high`

#### Scenario: A short text that is not a lookup
- **WHEN** a short text asks to explain why a design failed
- **THEN** the tier is not `light`

### Requirement: Everything else is standard
A text that is neither `complex` nor `light` SHALL classify as `standard`. The confidence is `low` when the verdict rests on no rule firing at all, and `high` when a rule ruled out the other two tiers.

#### Scenario: An ordinary question
- **WHEN** a 300-character question with no analysis vocabulary and one question mark is classified
- **THEN** the tier is `standard`

#### Scenario: Text the vocabulary cannot read
- **WHEN** a short text in a script the vocabulary does not cover is classified
- **THEN** only the length and question signals apply and the tier is `light` or `standard`, never an error

### Requirement: A labeled prompt set is the contract
The test suite SHALL hold a labeled set of at least 40 prompts, each with an expected tier and a mark of `clear` or `borderline`, covering every tier at least 10 times. Every `clear` prompt SHALL classify to its expected tier; every `borderline` prompt SHALL land within one tier of it. Changing a rule's threshold or vocabulary SHALL be done by changing this set first.

#### Scenario: The set passes
- **WHEN** the labeled set is classified
- **THEN** every clear prompt matches and every borderline prompt is at most one tier away

#### Scenario: A rule change is caught
- **WHEN** the complexity length threshold is raised above every long prompt in the set
- **THEN** the set test fails

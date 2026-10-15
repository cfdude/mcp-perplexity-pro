# Spec Delta

## Purpose
Defines the offline rules classifier that picks a tier (light, standard or complex) for a prompt, so dynamic routing can choose a model without a network call, and the labeled prompt set that pins its behavior.

## ADDED Requirements

### Requirement: The classifier is offline and deterministic
Classifying a text SHALL need no network, no database and no API key, SHALL cost nothing, SHALL record no usage event, and SHALL return the same result for the same text in every process, including under Python hash randomization.

#### Scenario: Same text, same result
- **WHEN** the same text is classified twice, in one process or two
- **THEN** both results are equal, signals included

#### Scenario: No side effects
- **WHEN** a text is classified during a call to `perplexity_ask` in dynamic mode
- **THEN** the only upstream request is the ask itself and the only usage event is the ask's

### Requirement: A result is a tier, signals and a reason
A classification SHALL return a tier (`light`, `standard` or `complex`), the ordered list of signal names that fired, and a reason of at most 120 ASCII characters built from those names and counts. The reason SHALL NOT contain any text taken from the prompt, because prompts can hold secrets and the reason is returned to the caller and may be logged.

#### Scenario: The reason names signals, not words
- **WHEN** a prompt containing the string `hunter2` is classified
- **THEN** the reason does not contain `hunter2` and names only signals such as length, question count or vocabulary count

### Requirement: Complexity signals raise the tier
A text SHALL classify as `complex` when any one of these holds: it contains at least two distinct entries of the fixed analysis vocabulary (compare, evaluate, trade-offs, pros and cons, step by step, root cause, architecture, in depth and similar, matched as whole words without regard to case); its trimmed length is at least 1200 characters; it holds three or more questions or numbered list items.

#### Scenario: Two analysis words
- **WHEN** the text asks to compare two libraries and evaluate their trade-offs
- **THEN** the tier is `complex` and the signals name the vocabulary

#### Scenario: A long text
- **WHEN** a text of 1500 characters with no analysis vocabulary and one question is classified
- **THEN** the tier is `complex` and the only signal is length

#### Scenario: Several questions
- **WHEN** a text holds three separate questions and no analysis vocabulary
- **THEN** the tier is `complex` and the only signal is the question count

#### Scenario: A question mark inside a URL is not a question
- **WHEN** a text holds two URLs with query strings and one question
- **THEN** it counts one question

### Requirement: Short lookups are light
A text SHALL classify as `light` when its trimmed length is at most 120 characters, it holds at most one question, it opens in a lookup form (what is, who is, when did, where is, how many, how much, define, latest, current, price of) and no complexity signal fired.

#### Scenario: A lookup
- **WHEN** the text is `What is the latest stable Python release?`
- **THEN** the tier is `light`

#### Scenario: A lookup without a question mark
- **WHEN** the text is `define idempotent`
- **THEN** the tier is `light`

#### Scenario: A short text that is not a lookup
- **WHEN** a short text asks to explain why a design failed
- **THEN** the tier is `standard`

### Requirement: Everything else is standard
A text that is neither `complex` nor `light` SHALL classify as `standard`.

#### Scenario: An ordinary question
- **WHEN** a 300-character question with no analysis vocabulary and one question mark is classified
- **THEN** the tier is `standard`

#### Scenario: Text the vocabulary cannot read
- **WHEN** a 60-character question in Japanese with one question mark is classified
- **THEN** only the length and question signals apply and the tier is `standard`, never an error

### Requirement: A labeled prompt set is the contract
The test suite SHALL hold a labeled set of at least 40 prompts, each with an expected tier and a mark of `clear` or `borderline`, covering every tier at least 10 times and, for each complexity signal and the lookup rule, at least one clear prompt that triggers only that signal. Every `clear` prompt SHALL classify to its expected tier; every `borderline` prompt SHALL land within one tier. Changing a rule SHALL be done by changing this set first.

#### Scenario: The set passes
- **WHEN** the labeled set is classified
- **THEN** every clear prompt matches and every borderline prompt is at most one tier away

#### Scenario: A rule change is caught
- **WHEN** the length threshold is raised above every long prompt in the set, or the question-count threshold above three
- **THEN** the set test fails

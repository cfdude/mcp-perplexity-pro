# Spec Delta

## ADDED Requirements

### Requirement: A text has a task class
The rules SHALL return for any text a task class, `coding`, `reasoning` or `browsing`, offline and deterministic, and independent of the tier. The class is `coding` when the text contains a fenced code block (three backticks) or a phrase of the coding vocabulary, else `reasoning` when it contains a phrase of the reasoning vocabulary, else `browsing`. Phrases match as whole words without regard to case. No reason SHALL contain prompt text.

#### Scenario: Coding vocabulary
- **WHEN** the text is `Why does this traceback appear when I run the unit tests?`
- **THEN** the task class is `coding`

#### Scenario: A fenced block
- **WHEN** the text holds a fenced code block and no vocabulary word
- **THEN** the task class is `coding`

#### Scenario: Reasoning vocabulary
- **WHEN** the text is `Prove that the sum of two even numbers is even.`
- **THEN** the task class is `reasoning`

#### Scenario: A lookup is browsing and light
- **WHEN** the text is `What is the latest stable Python release?`
- **THEN** the task class is `browsing` and the tier is `light`

#### Scenario: A language name alone is not coding
- **WHEN** the text is `Which Python version is newer, 3.12 or 3.13?` with no vocabulary phrase
- **THEN** the task class is `browsing`

#### Scenario: Coding wins over reasoning
- **WHEN** the text holds a coding phrase and a reasoning phrase
- **THEN** the task class is `coding`

#### Scenario: Class does not move the tier
- **WHEN** the labeled prompt set is classified
- **THEN** every prompt's tier equals its existing label and every class equals its new label

#### Scenario: Deterministic and total
- **WHEN** any string, including an empty one, is classified twice
- **THEN** both results are equal and none raises

### Requirement: The coding vocabulary is fixed
The coding vocabulary SHALL be exactly: `traceback`, `stack trace`, `stacktrace`, `segfault`, `syntax error`, `compile error`, `compiler error`, `unit test`, `refactor`, `refactored`, `refactoring`, `regex`, `regular expression`, `pull request`, `code review`, `debugging`, `source code`, `codebase`, each also as a plural where it has one. Generic words and language names SHALL NOT be in it.

#### Scenario: A listed phrase
- **WHEN** the text contains `regular expression`
- **THEN** the task class is `coding`

#### Scenario: A plural
- **WHEN** the text contains `stack traces`
- **THEN** the task class is `coding`

#### Scenario: Generic words
- **WHEN** the text is `Is this function a bug?` with no listed phrase
- **THEN** the task class is `browsing`

### Requirement: The reasoning vocabulary is fixed
The reasoning vocabulary SHALL be exactly these whole words and phrases: `prove`, `proves`, `proved`, `proven`, `proof`, `proofs`, `derive`, `derives`, `derived`, `derivation`, `derivations`, `theorem`, `theorems`, `lemma`, `lemmas`, `probability`, `probabilities`, `equation`, `equations`, `integral`, `integrals`, `eigenvalue`, `eigenvalues`, `logic puzzle`, `logic puzzles`.

#### Scenario: A listed word
- **WHEN** the text contains `eigenvalues` and no coding phrase
- **THEN** the task class is `reasoning`

#### Scenario: An inflection
- **WHEN** the text asks how the formula was `derived`
- **THEN** the task class is `reasoning`

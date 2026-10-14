## ADDED Requirements

### Requirement: Invalid requests point to help
A tool failure with category `invalid_request` raised by any tool other than `perplexity_help` SHALL end its message with one sentence naming the help call for that tool: `Call perplexity_help with action "tool" and name "<tool>" for its arguments and examples.` The category, the structured `category` and every other part of the message SHALL be unchanged, and no other category SHALL gain the sentence.

#### Scenario: A bad argument
- **WHEN** a client calls `perplexity_ask` with a depth `turbo`
- **THEN** the error is `invalid_request`, its message states the depth problem and ends with the sentence naming `perplexity_help` and `perplexity_ask`

#### Scenario: Argument validation by the framework
- **WHEN** a client passes a value of the wrong type to a tool
- **THEN** the same sentence is appended to that `invalid_request`

#### Scenario: Other categories are untouched
- **WHEN** an upstream call fails with `rate_limited`
- **THEN** the message has no help sentence

#### Scenario: Help's own errors
- **WHEN** a client asks `perplexity_help` for an unknown tool
- **THEN** the message lists the valid names and has no extra help sentence

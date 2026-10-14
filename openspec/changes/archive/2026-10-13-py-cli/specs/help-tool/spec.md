## ADDED Requirements

### Requirement: Help renders for the command line
The help renderers SHALL take a style, `mcp` (the default) or `cli`. In `cli` style an example is written as a `perplexity-pro` command line derived from the same example arguments, and the closing pointer names `perplexity-pro help`. Topic pages SHALL be identical in both styles. Every example, rendered to a command line and parsed back by the CLI parser, SHALL yield the same arguments.

#### Scenario: A command-line example
- **WHEN** the tool page for `perplexity_ask` is rendered in `cli` style
- **THEN** its example is a `perplexity-pro ask ...` line and not a JSON call

#### Scenario: Examples round-trip
- **WHEN** each tool's example is rendered as a command line and parsed
- **THEN** the parsed arguments equal the example arguments

#### Scenario: Topics are the same
- **WHEN** a topic page is rendered in both styles
- **THEN** the two texts are identical

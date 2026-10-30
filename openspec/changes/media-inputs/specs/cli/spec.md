# cli Specification

## ADDED Requirements

### Requirement: The command takes attachments
`perplexity-pro ask` and `perplexity-pro chat` SHALL accept `--attachments VALUE`, repeatable, generated from the tool schema like any list of strings, and `--help` for the two subcommands SHALL list it. `research` and every other subcommand SHALL NOT have it.

#### Scenario: Repeated flags
- **WHEN** a user passes `--attachments a.png --attachments https://example.com/b.pdf`
- **THEN** the tool receives both, in that order

#### Scenario: Research has no flag
- **WHEN** a user runs `perplexity-pro research --help`
- **THEN** no `--attachments` flag is listed

### Requirement: Paths are made absolute by the command
The command SHALL make a relative path argument absolute against its own working directory and expand a leading `~/` before calling the tool (the tool refuses relative paths), and SHALL leave `https://` URLs, `data:` strings and `<media type>::` prefixed values unchanged.

#### Scenario: A relative path
- **WHEN** a user runs `perplexity-pro ask "What is this?" --attachments shot.png --model openai/gpt-6-luna` in a directory holding `shot.png`
- **THEN** the tool receives the absolute path of that file and the answer is printed

### Requirement: Attachment refusals print as errors
A refusal of an attachment SHALL print `[invalid_request] ...` on standard error, exit 1 and make no request, as every local refusal does.

#### Scenario: A refusal
- **WHEN** a user passes `--attachments call.mp3`
- **THEN** the command prints `[invalid_request]` naming audio on standard error, exits 1 and makes no request

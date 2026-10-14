## ADDED Requirements

### Requirement: The perplexity-pro command
The package SHALL install a console command `perplexity-pro` with one subcommand per registered tool, named without the `perplexity_` prefix, and a `serve` subcommand that runs the MCP server with the same `--transport` choices as `mcp-perplexity-pro`. The existing `mcp-perplexity-pro` command SHALL keep its arguments, behavior and exit codes unchanged.

#### Scenario: Subcommands
- **WHEN** a user runs `perplexity-pro --help`
- **THEN** the help lists `ask`, `chat`, `research`, `jobs`, `search`, `decide`, `embed`, `models`, `projects`, `usage`, `help` and `serve`

#### Scenario: The old command
- **WHEN** a user runs `mcp-perplexity-pro --transport http`
- **THEN** it serves exactly as before

### Requirement: Subcommands come from the tool schemas
Each tool subcommand and its flags SHALL be generated from that tool's input schema, so a parameter added to a tool appears as a flag without an edit to the CLI, and the flag's help SHALL be the schema's description. Building the parser SHALL need no API key, no network and no data directory.

#### Scenario: A new parameter
- **WHEN** a tool gains a parameter
- **THEN** its subcommand accepts the matching flag and `--help` shows the schema description

#### Scenario: Offline parser
- **WHEN** the parser is built with an empty environment
- **THEN** no socket is opened, no file is created and no setting is read

### Requirement: Positionals and flags
A required `action` and a required `query` SHALL be positionals (in that order, when present); every other parameter SHALL be a `--flag` named with dashes, so `perplexity-pro chat send --title t --message hello` and `perplexity-pro ask "q" --depth fast` are the forms. `--args-json` SHALL merge a JSON object of arguments, with explicit flags winning.

#### Scenario: Positionals and flags
- **WHEN** a user runs `perplexity-pro ask "what is new in Python?" --depth fast --domains python.org --domains docs.python.org`
- **THEN** the tool is called with `query`, `depth` `fast` and a two-element `domains` list

#### Scenario: Escape hatch
- **WHEN** a user runs `perplexity-pro decide --args-json '{"state": "...", "questions": {...}}'`
- **THEN** the tool is called with those arguments, and a flag given as well overrides the same key

### Requirement: Value types and refusals
A boolean SHALL be `--flag` and `--no-flag`; a list of strings SHALL be given by repeating the flag; an object or an array of objects SHALL be a JSON string, `@path` (a file) or `-` (standard input). A value of the wrong type or an unknown enum value SHALL be refused with exit status 2 naming the flag, before any setup or call.

#### Scenario: JSON from a file
- **WHEN** a user runs `perplexity-pro ask "q" --json-schema @schema.json`
- **THEN** the tool is called with the parsed file as `json_schema`

#### Scenario: A bad value
- **WHEN** a user runs `perplexity-pro search "q" --max-results many`
- **THEN** the command exits 2 naming `--max-results` and nothing was set up or sent

#### Scenario: Booleans
- **WHEN** a user runs `perplexity-pro ask "q" --no-search`
- **THEN** the tool is called with `search` false

### Requirement: Output and exit codes
A successful command SHALL print the tool's readable text to standard output, or with `--json` the structured result as JSON, and exit 0. A tool failure SHALL print `[category] message` to standard error and exit 1. An interrupted command SHALL exit 130. Logging SHALL go to standard error only.

#### Scenario: Text and JSON
- **WHEN** a user runs `perplexity-pro models --json`
- **THEN** standard output is one JSON document that parses and equals the tool's structured result

#### Scenario: A tool error
- **WHEN** a user runs `perplexity-pro ask "q" --depth high`
- **THEN** standard error shows `[invalid_request] ...`, standard output is empty and the exit status is 1

### Requirement: One code path with the tools
Every command SHALL call the registered tool in-process, so routing resolution, validation, project rules, usage recording and error categories are those of the MCP tool. A costed command SHALL record exactly one usage event, in the same database the server uses.

#### Scenario: A costed command
- **WHEN** `perplexity-pro ask "q"` completes against a mocked upstream
- **THEN** exactly one usage event exists with tool `perplexity_ask` and the routing mode's default model

#### Scenario: Routing applies
- **WHEN** the environment sets `PERPLEXITY_ROUTING=custom` with three tiers and a user runs `perplexity-pro ask "q" --tier light`
- **THEN** the call names the light tier's model, as over MCP

### Requirement: Help follows CLI conventions and the shared text
`perplexity-pro --help` and `perplexity-pro <command> --help` SHALL be ordinary help (usage, arguments, flags) and a command's help SHALL include the tool's summary, cost line and example from the shared help text. `perplexity-pro help` SHALL print the index, `help <tool>` (with or without the `perplexity_` prefix) a tool page and `help <topic>` a topic page, byte for byte the text `perplexity_help` returns. None of these SHALL need an API key, the network or a data directory.

#### Scenario: Help without a key
- **WHEN** a user runs `perplexity-pro help ask` with an empty environment
- **THEN** the tool page for `perplexity_ask` is printed and the exit status is 0

#### Scenario: Same text as the MCP tool
- **WHEN** `perplexity-pro help costs` is compared with `perplexity_help` `topic` `costs` on a default server
- **THEN** the two texts are identical

#### Scenario: Unknown name
- **WHEN** a user runs `perplexity-pro help pricing`
- **THEN** the command exits 1 and lists the valid tool and topic names

### Requirement: Version
`perplexity-pro --version` SHALL print the package version and need no key.

#### Scenario: Version
- **WHEN** a user runs `perplexity-pro --version` with an empty environment
- **THEN** the version prints and the exit status is 0

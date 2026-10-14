## ADDED Requirements

### Requirement: The perplexity-pro command
The package SHALL install a console command `perplexity-pro` with one subcommand per registered tool, named without the `perplexity_` prefix, and a `serve` subcommand that runs the MCP server with the same `--transport` choices as `mcp-perplexity-pro` (so each transport has two documented commands). The existing `mcp-perplexity-pro` command SHALL keep its arguments, behavior and exit codes unchanged.

#### Scenario: Subcommands
- **WHEN** a user runs `perplexity-pro --help`
- **THEN** the help lists `ask`, `chat`, `research`, `jobs`, `search`, `decide`, `embed`, `models`, `projects`, `usage`, `help` and `serve`

#### Scenario: The old command
- **WHEN** a user runs `mcp-perplexity-pro --transport http`
- **THEN** it serves exactly as before

### Requirement: Subcommands come from the tool schemas
Each tool subcommand and its flags SHALL be generated from that tool's input schema (`help` excepted, which is written by hand), so a parameter added to a tool appears as a flag without an edit to the CLI, and the flag's help SHALL be the schema's description. Building the parser SHALL need no API key, no network and no data directory.

#### Scenario: A new parameter
- **WHEN** a tool gains a parameter
- **THEN** its subcommand accepts the matching flag and `--help` shows the schema description

#### Scenario: Offline parser
- **WHEN** the parser is built with an empty environment
- **THEN** no socket is opened, no file is created and no key is needed

### Requirement: Positionals and flags
A required `action` and a required `query` SHALL be positionals (in that order, when present); every other parameter SHALL be a `--flag` named with dashes, so `perplexity-pro chat send --title t --message hello` and `perplexity-pro ask "q" --depth fast` are the forms. `--args-json` (a JSON object, `@path` or `-`) SHALL merge arguments, with explicit flags winning. Required parameters SHALL be checked after that merge, so a value may come from either; one still missing SHALL exit 2 naming it.

#### Scenario: Positionals and flags
- **WHEN** a user runs `perplexity-pro ask "what is new in Python?" --depth fast --domains python.org --domains docs.python.org`
- **THEN** the tool is called with `query`, `depth` `fast` and a two-element `domains` list

#### Scenario: Escape hatch
- **WHEN** a user runs `perplexity-pro decide --args-json '{"state": "...", "questions": {...}}'`
- **THEN** the tool is called with those arguments, and a flag given as well overrides the same key

#### Scenario: A required value still missing
- **WHEN** a user runs `perplexity-pro ask` with no query and no `--args-json`
- **THEN** the command exits 2 naming `query`, and nothing was set up or sent

#### Scenario: A value starting with a dash
- **WHEN** a user runs `perplexity-pro search "q" --domains=-reddit.com`
- **THEN** the tool is called with the denylist domain `-reddit.com`, and `--` ends the flags so a query that starts with a dash can follow

### Requirement: Value types
A null union SHALL be unwrapped (an omitted parameter is never sent, not even as null); a string, integer or number SHALL be typed accordingly; a boolean SHALL be `--flag` and `--no-flag` and unset by default; a list of strings SHALL be given by repeating the flag. Abbreviated flags SHALL NOT be accepted.

#### Scenario: Booleans and untouched parameters
- **WHEN** a user runs `perplexity-pro ask "q" --no-search`
- **THEN** the tool is called with `search` false and no other optional key

### Requirement: Structured and untyped values
An object, an array of objects, or a parameter with no declared type SHALL be a JSON string, `@path` (a file) or `-` (standard input); a value with no declared type SHALL be parsed as JSON when it is an object or array and kept as text otherwise. A parameter whose schema allows a string or a list of strings (the search `query`) SHALL be a positional that takes one or more values and sends a string for one and a list for several.

#### Scenario: JSON from a file
- **WHEN** a user runs `perplexity-pro ask "q" --json-schema @schema.json`
- **THEN** the tool is called with the parsed file as `json_schema`

#### Scenario: Several search queries
- **WHEN** a user runs `perplexity-pro search "rust borrow checker" "zig comptime"`
- **THEN** the tool is called with a two-element `query` list, and with one query a plain string

#### Scenario: Untyped text or JSON
- **WHEN** a user runs `perplexity-pro decide --state "a ticket text" --questions @q.json` and later with `--state '{"a": 1}'`
- **THEN** the first sends the state as text and the second as an object

### Requirement: Local refusals
A value of the wrong type, a value outside a schema `enum`, an unknown flag or an abbreviated flag SHALL be refused with exit status 2 naming the flag, before any setup or call. A value the schema only describes in words (a depth, a tier, a recency, an action) SHALL reach the tool, which refuses it as a tool error (exit 1).

#### Scenario: A bad value
- **WHEN** a user runs `perplexity-pro search "q" --max-results many`
- **THEN** the command exits 2 naming `--max-results` and nothing was set up or sent

#### Scenario: A schema enum
- **WHEN** a user runs `perplexity-pro usage --group-by hour`
- **THEN** the command exits 2 listing the allowed values

#### Scenario: A described value is the tool's to refuse
- **WHEN** a user runs `perplexity-pro ask "q" --depth turbo`
- **THEN** the tool refuses it, standard error shows `[invalid_request] ...` and the exit status is 1

### Requirement: Output
A successful command SHALL print the tool's readable text to standard output, or with `--json` the structured result as JSON, and exit 0. Logging SHALL go to standard error only, and a closed pipe SHALL end the command quietly.

#### Scenario: Text and JSON
- **WHEN** a user runs `perplexity-pro models --json`
- **THEN** standard output is one JSON document that parses and equals the tool's structured result

### Requirement: Exit codes and cleanup
A tool failure SHALL print `[category] message` to standard error and exit 1, with the MCP help sentence replaced by `Run perplexity-pro help <command> for its arguments and examples.` A setup failure (a missing key, an invalid setting, a failed migration) SHALL print the startup message and exit 1. An interrupted command SHALL exit 130, still recording a call the provider had accepted, and every path SHALL close the upstream client and the database engine.

#### Scenario: A tool error
- **WHEN** a user runs `perplexity-pro ask "q" --depth high`
- **THEN** standard error shows `[invalid_request] ...` ending with the CLI help sentence (not the MCP one), standard output is empty and the exit status is 1

#### Scenario: A setup failure
- **WHEN** a user runs `perplexity-pro ask "q"` with no `PERPLEXITY_API_KEY`
- **THEN** standard error names `PERPLEXITY_API_KEY`, the exit status is 1 and no data directory was created

#### Scenario: Interrupted
- **WHEN** a user presses Ctrl-C while a call is in flight
- **THEN** the exit status is 130 and the usage event of a call the provider already answered is still recorded

#### Scenario: Resources are closed
- **WHEN** a command fails or is interrupted after setup
- **THEN** the upstream client and the database engine are closed

### Requirement: One code path with the tools
Every command except `help` SHALL call the registered tool in-process, so routing resolution, validation, project rules, usage recording and error categories are those of the MCP tool. A costed command SHALL record exactly one usage event, in the same database the server uses.

#### Scenario: A costed command
- **WHEN** `perplexity-pro ask "q"` completes against a mocked upstream
- **THEN** exactly one usage event exists with tool `perplexity_ask` and the routing mode's default model

#### Scenario: Routing applies
- **WHEN** the environment sets `PERPLEXITY_ROUTING=custom` with three tiers and a user runs `perplexity-pro ask "q" --tier light`
- **THEN** the call names the light tier's model, as over MCP

### Requirement: Command help
`perplexity-pro --help` and `perplexity-pro <command> --help` SHALL be ordinary help (usage, arguments, flags with schema defaults and descriptions), and a command's help SHALL include the tool's summary, cost line and an example written as a command line.

#### Scenario: A command's help
- **WHEN** a user runs `perplexity-pro ask --help`
- **THEN** the output shows the usage line, every flag with its schema description and default, the tool's cost line and a `perplexity-pro ask ...` example

### Requirement: The help subcommand
`perplexity-pro help` SHALL print the index, `help <tool>` (with or without the `perplexity_` prefix) a tool page and `help <topic>` a topic page, from the shared help text in its command-line style: the same data as `perplexity_help`, differing only in the example lines and the closing pointer, and identical for topic pages.

#### Scenario: Same data as the MCP tool
- **WHEN** `perplexity-pro help costs` is compared with `perplexity_help` `topic` `costs` on a default server, and again for the routing topic on a `custom` server
- **THEN** the two texts are identical

#### Scenario: Unknown name
- **WHEN** a user runs `perplexity-pro help pricing`
- **THEN** the command exits 1 and lists the valid tool and topic names

### Requirement: Help needs nothing
`--help`, `help` and `--version` SHALL need no API key, no network and no data directory, and SHALL NOT fail on an invalid environment: they read settings with a placeholder key and, when the environment is invalid, fall back to the default routing with one warning on standard error.

#### Scenario: Help without a key
- **WHEN** a user runs `perplexity-pro help ask` with an empty environment
- **THEN** the tool page for `perplexity_ask` is printed with a command-line example and the exit status is 0

#### Scenario: A broken environment
- **WHEN** a user runs `perplexity-pro help` with `PERPLEXITY_PORT=nope`
- **THEN** the index prints with default routing, one warning is on standard error and the exit status is 0

### Requirement: Version
`perplexity-pro --version` SHALL print the package version and need no key.

#### Scenario: Version
- **WHEN** a user runs `perplexity-pro --version` with an empty environment
- **THEN** the version prints and the exit status is 0

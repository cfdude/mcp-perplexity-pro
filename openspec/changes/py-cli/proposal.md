# Proposal

## Why

CLIs are becoming the other way agents and people reach a tool, and Rob asked (2026-10-13) for this server to be usable as an MCP server or as a command line, before it is published to PyPI so that someone who finds the package gets both. Today the only command is `mcp-perplexity-pro --transport stdio|http`, which serves MCP and nothing else. All the behavior already exists behind eleven tools; the CLI must not re-implement it (a second code path for routing, validation, recording or cost would drift), and it needs the help text the previous change put in one module for exactly this.

## What Changes

- Add a console command `perplexity-pro` with one subcommand per tool, named without the prefix: `ask`, `chat`, `research`, `jobs`, `search`, `decide`, `embed`, `models`, `projects`, `usage`, `help`, plus `serve` (the MCP server, the same flags as today). `mcp-perplexity-pro` stays exactly as it is, so pm2 and every MCP client configuration keep working.
- The CLI calls the real tools in-process (the same `build_server` and the same tool functions through an in-process FastMCP client), so validation, routing modes, usage recording, project rules, error categories and costs are the ones the MCP tools have, with one code path.
- The subcommands and their flags are generated from each tool's input schema, so a parameter added to a tool appears on the command line without an edit. The mapping is fixed and small: a required `action` and a required `query` are positionals, every other parameter is a `--flag` (booleans as `--flag/--no-flag`, lists by repeating the flag, JSON objects and arrays from a JSON string, `@file` or `-` for stdin), and `--args-json` merges a whole argument object as an escape hatch.
- Output: the tool's readable text on stdout by default; `--json` prints its structured result. A tool error prints `[category] message` on stderr and exits 1; a usage error exits 2 (argparse); a Ctrl-C exits 130.
- Help follows normal CLI patterns: `perplexity-pro --help`, `perplexity-pro <command> --help` (generated flags, with the tool's summary, cost line and example from the shared help text) and `perplexity-pro help [<tool> | <topic>]`, which prints the same text `perplexity_help` returns. `--help`, `help` and `--version` need no API key, no network and no data directory.
- No new dependency: the parser is `argparse`.
- Out of scope: PyPI publishing and the install story (`pypi-publish`), shell completion, a config file, colour, streaming output, an interactive chat loop, a dry-run flag, Windows.

## Capabilities

### New Capabilities

- `cli`: the `perplexity-pro` command, the generation of subcommands from tool schemas, the argument mapping, the output and exit-code contract and the help behavior.

### Modified Capabilities

- None (`mcp-perplexity-pro` and every MCP behavior are unchanged; the console-script table in `pyproject.toml` gains one entry).

## Impact

- **Code:** new `src/mcp_perplexity_pro/cli_app.py` (the command; `cli.py` keeps the server's own parser), a second entry in `[project.scripts]`, and a small refactor of `__main__.py` so the bootstrap can be reused without serving.
- **Tests:** new `tests/test_cli_parser.py`, `tests/test_cli_run.py` and a subprocess test; existing tests untouched.
- **Spend:** the CLI makes the same costed calls the tools do and every one is recorded in the same database; live acceptance spends under $0.01.
- **Dependencies, migration, tool surface:** none.

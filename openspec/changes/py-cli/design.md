## Context

Rob asked for "MCP or CLI, whichever the finder prefers", with normal `--help` on the CLI. The previous change (`agent-help`) put every help string in the pure `help_text` module so the CLI could print it, and made the tool schemas the source of every argument description. The server builds without disk or network when given a throwaway in-memory engine (probed 2026-10-13: `build_server(Settings(api_key="unused"), httpx2.AsyncClient(), create_async_engine("sqlite+aiosqlite://"))` returns a FastMCP object), which is what lets the parser be generated before any setup.

## Goals / Non-Goals

**Goals:** one code path with the MCP tools; flags that cannot drift from the tools; normal CLI ergonomics (`--help`, exit codes, stdout versus stderr, JSON when asked); help without a key.

**Non-Goals:** a second implementation of any tool, a REPL, completion, a config file, publishing.

## Decisions

**D1. Two commands, one package.** `perplexity-pro <subcommand>` is new; `mcp-perplexity-pro` is untouched (its parser, its `--transport`, its exit codes), because pm2 and client configs call it. `perplexity-pro serve` takes the same `--transport` and is the server through the new command, so a person who installs the package learns one command name.

**D2. In-process calls through the tools.** The CLI runs `bootstrap` (settings, migrations, database, upstream client: the order the server-runtime spec requires) and calls tools with an in-process `fastmcp.Client(server)`. Nothing is re-implemented, so a routing mode, a refusal, a usage event or an error category is the same as over MCP. The cost: a call goes through the MCP framing in memory; negligible next to an API call.

**D3. The parser is generated from the tool schemas, offline.** A first step builds the server over an unused in-memory engine and a client that is never used, reads each tool's input schema and builds one `argparse` subparser per tool. No key, no disk, no network; this is what makes `--help` work with an empty environment. A test pins that building the parser touches none of them.

**D4. A fixed, small argument mapping.** Positionals: `action` when the tool requires it, then `query` when required (`chat` requires only `action`, so a message is `chat send --title t --message hello`). Every other parameter is a `--flag` with the schema's type: string, integer, number; boolean as `--flag` and `--no-flag`; a list of strings by repeating the flag; an object or an array of objects (`json_schema`, `questions`, `state`, `items`) as a JSON string, `@path` to read a file or `-` for stdin. Enum parameters list their values in `--help`. `--args-json` merges a whole JSON object of arguments (flags win), so any call the schema allows can be made. Unknown or mistyped values are refused locally with exit 2 naming the flag, before bootstrap and before any call.

**D5. Output and exit codes.** Default stdout is the tool's text content (what an MCP client shows), `--json` prints the structured content (indented on a terminal, compact when piped). Tool failures print `[category] message` to stderr and exit 1 (the category is the closed vocabulary); argparse usage errors exit 2; interrupted exits 130 (a call in flight is cancelled, and the usage recorder's shielded write still lands, as over MCP). Logging stays on stderr, so stdout is the answer.

**D6. Help uses the shared text.** `perplexity-pro --help` and `<command> --help` are ordinary argparse help (usage line, flags, the tool's summary and example from `help_text` as description and epilog). `perplexity-pro help` with no argument prints the index, `help <tool>` (with or without the `perplexity_` prefix) a tool page, `help <topic>` a topic page: the same functions the `perplexity_help` tool calls, with the tool schemas of the offline server, so the text is identical. None of it needs a key, the network or a data directory.

**D7. Billing stays visible.** Every costed command prints the usage line the tool already puts in its text (cost, tokens, latency, project); the CLI adds nothing to hide or add. There is no cost ceiling, as for the tools.

**D8. No new dependency.** `argparse` is enough for the mapping above; click or typer would add a dependency to a package about to be published and would still need the schema generation. The cost is generation code that this change tests thoroughly.

**D9. Reuse over refactor.** `__main__.py` already separates `bootstrap()` from `run()`. The CLI imports `bootstrap` and `close_resources`; the only change there is that `bootstrap` accepts being called by the CLI (it already is a plain function). The signal handling of `run()` is for serving and is not reused.

## Risks / Trade-offs

- **Generated flags may read poorly for an odd schema.** Mitigation: the mapping is fixed, `--help` shows the schema description and the tool's example, and `--args-json` always works.
- **In-process MCP framing hides nothing but adds a layer.** Accepted (D2): one code path is worth more than a few milliseconds.
- **A mistyped flag after a costed positional could still bill.** Local validation happens before bootstrap and the tool validates before sending (as over MCP), so a refused call is never billed.
- **Two commands to document.** README leads with one table: `perplexity-pro <tool>` and `serve`.

## Migration Plan

None. The old command is unchanged; the new one is additive.

## Open Questions

None blocking. Shell completion and a config file are deferred until someone asks.

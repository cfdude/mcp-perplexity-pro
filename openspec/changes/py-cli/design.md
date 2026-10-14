## Context

Rob asked for "MCP or CLI, whichever the finder prefers", with normal `--help` on the CLI. The previous change (`agent-help`) put every help string in the pure `help_text` module so the CLI could print it, and made the tool schemas the source of every argument description. The server builds without disk or network when given a throwaway in-memory engine (probed 2026-10-13: `build_server(Settings(api_key="unused"), httpx2.AsyncClient(), create_async_engine("sqlite+aiosqlite://"))` returns a FastMCP object), which is what lets the parser be generated before any setup.

## Goals / Non-Goals

**Goals:** one code path with the MCP tools; flags that cannot drift from the tools; normal CLI ergonomics (`--help`, exit codes, stdout versus stderr, JSON when asked); help without a key.

**Non-Goals:** a second implementation of any tool, a REPL, completion, a config file, publishing.

## Decisions

**D1. Two commands, one package.** `perplexity-pro <subcommand>` is new; `mcp-perplexity-pro` is untouched (its parser, its `--transport`, its exit codes), because pm2 and client configs call it. `perplexity-pro serve` takes the same `--transport` and is the server through the new command, so a person who installs the package learns one command name.

**D2. In-process calls through the tools.** The CLI runs `bootstrap` (settings, migrations, database, upstream client: the order the server-runtime spec requires) and calls tools with an in-process `fastmcp.Client(server)`. Nothing is re-implemented, so a routing mode, a refusal, a usage event or an error category is the same as over MCP. The cost: a call goes through the MCP framing in memory; negligible next to an API call.

**D3. The parser is generated from the tool schemas, offline.** A first step builds the server over an unused in-memory engine and a client that is never used, reads each tool's input schema and builds one `argparse` subparser per tool. No key, no disk, no network; this is what makes `--help` work with an empty environment. A test pins that building the parser touches none of them.

**D4. A fixed, small argument mapping, written down against the real schemas.** Probed 2026-10-13: every optional parameter is `anyOf [T, null]` (unwrap, never send an omitted one); `perplexity_search.query` is a string or a list of strings; `perplexity_decide` requires `state` (no declared type: text or a JSON object or list) and `questions` (an object); `perplexity_help` has an optional `action`; and only `perplexity_projects.action` and `perplexity_usage.group_by` carry a schema `enum` (a depth, a tier, a recency and most actions are plain strings described in words). So: positionals are a required `action` then a required `query` (a string-or-list query takes one or more values); everything else is a `--flag` (`chat` requires only `action`, so a message is `chat send --title t --message hello`); booleans are `--flag/--no-flag`, unset by default; lists repeat the flag; objects, arrays of objects and untyped values are a JSON string, `@path` or `-`, an untyped value parsed as JSON only when it is an object or array. `--args-json` (JSON, `@path` or `-`) is merged first and explicit flags win; required parameters are therefore checked after the merge (argparse positionals and required flags are optional at parse time). Only schema enums, types and unknown or abbreviated flags are refused locally (exit 2, before setup); a described value such as `--depth turbo` is the tool's to refuse (exit 1) because moving those into schema enums would change `tools/list` against its size budget. A value that starts with a dash uses `--flag=-value` or `--`. `help` is the one hand-written subcommand.

**D5. Output and exit codes.** Default stdout is the tool's text content (what an MCP client shows), `--json` prints the structured content (indented on a terminal, compact when piped). Tool failures print `[category] message` to stderr and exit 1 (the category is the closed vocabulary); a setup failure (missing key, invalid setting, failed migration) prints `bootstrap`'s message and exits 1; argparse usage errors exit 2; interrupted exits 130 (a call in flight is cancelled, and the usage recorder's shielded write still lands, as over MCP, proven by a subprocess test with a slow loopback upstream). Every path closes the client and the engine (mutation-checked). Logging stays on stderr, so stdout is the answer.

**D6. Help uses the shared text in a command-line style.** `help_text`'s renderers gain a `style` (`mcp` default, `cli`): in `cli` style the example is a `perplexity-pro` command line derived from the same example dict, the closing pointer names `perplexity-pro help`, and topic pages are unchanged. `perplexity-pro --help` and `<command> --help` are argparse help (flags with schema defaults and descriptions) with the tool's summary, cost line and CLI example as description and epilog. `perplexity-pro help [<tool>|<topic>]` calls the same renderers over the offline server's schemas (probed: byte-identical to the MCP tool's text in `mcp` style). A tool error's MCP sentence (`Call perplexity_help with ...`, appended by the server) is replaced on stderr by `Run perplexity-pro help <command> for its arguments and examples.` Help needs settings only for the routing line, so it loads them with a placeholder key and, on an invalid environment, falls back to default routing with one warning; it never needs a key, the network or a data directory.

**D7. Billing stays visible.** Every costed command prints the usage line the tool already puts in its text (cost, tokens, latency, project); the CLI adds nothing to hide or add. There is no cost ceiling, as for the tools.

**D8. No new dependency.** `argparse` is enough for the mapping above; click or typer would add a dependency to a package about to be published and would still need the schema generation. The cost is generation code that this change tests thoroughly.

**D9. Reuse with two small parameters.** `__main__.py` already separates `bootstrap()` from `run()`. `bootstrap` gains `http` (an upstream client to use instead of building one, so tests inject a `MockTransport` and the startup order stays in one place) and `serving` (default true; the non-loopback host warning is only for a process that listens). The CLI imports `bootstrap` and `close_resources`; the signal handling of `run()` is for serving and is not reused. `FASTMCP_CHECK_FOR_UPDATES=off` is set before the first FastMCP import in the CLI module, because the offline parser is built before `bootstrap` runs. Schemas are read with `tool.parameters` (not the deprecated `inputSchema`). Output: tool failures are read from the in-process client's result (no framework log noise), stdout carries only the answer, a `BrokenPipeError` ends quietly, Ctrl-C during setup or a call exits 130 after closing the client and engine.

## Risks / Trade-offs

- **Generated flags may read poorly for an odd schema.** Mitigation: the mapping is fixed, `--help` shows the schema description and the tool's example, and `--args-json` always works.
- **In-process MCP framing hides nothing but adds a layer.** Accepted (D2): one code path is worth more than a few milliseconds.
- **A mistyped flag after a costed positional could still bill.** Local validation happens before bootstrap and the tool validates before sending (as over MCP), so a refused call is never billed.
- **Two commands to document.** README leads with one table: `perplexity-pro <tool>` and `serve`.

## Migration Plan

None. The old command is unchanged; the new one is additive.

## Open Questions

None blocking. Shell completion and a config file are deferred until someone asks.

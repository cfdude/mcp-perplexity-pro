# Call-site sweep and commit verification (tasks 6.1 and 6.2)

Derived with `rg` by the Gate 2 reviewer over ab0cd1b..cbce774; findings fixed in the next commit.

| Rule | Sites | Holds |
|---|---|---|
| every tool has a subcommand | 11 `register(` calls; `--help` of all 11 works; 53 string, 15 integer, 8 boolean, 4 list, 3 json, 1 untyped, 1 number and 1 string-or-list parameters all parse | yes |
| abbreviations refused | `allow_abbrev=False` on the top-level parser and every subparser | yes |
| `bootstrap()` callers | `__main__.main`, `command.run_tool` (`http`, `serving=False`), `command.serve`, two test helpers | yes; the old command is unchanged |
| stdout and stderr writes | `command.py` only; logs and errors go to stderr, stdout is the answer | yes |
| process-global state | `PERPLEXITY_LOG_LEVEL` and the `fastmcp` logger level restored in `finally`; no signal handlers in `command.py` | yes on success, tool error, `SystemExit` from bootstrap, interrupt |
| exit codes | 0, 1 (tool error, setup failure), 2 (argparse), 130 (interrupt), quiet end on a closed pipe | yes |
| `help_text` renderer callers | `tools/help.py` (mcp style), `command.py` (cli style, examples passed in) | yes |
| startup cost | `--version` and `serve` no longer build the schemas (1.0 s to 0.13 s) | fixed |
| inverses | a flag refusable by type (`--max-results abc`), `serve` stops on SIGINT and SIGTERM | yes |

Commit verification (`git show --stat`): 1.1 `dac603f`, 2.1 `157e73c`, 3.1 `d769c2d`, 4.1 `9860c2e` each contain the files their task claims; the self-contained-package claim of 4.1 was reworded to what the test proves.

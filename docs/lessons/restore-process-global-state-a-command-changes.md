---
name: restore-process-global-state-a-command-changes
kind: process-failure
trigger: Writing code that a test calls in-process and that sets a process-global (a logger level, an environment variable, a signal handler) to make a command quieter or safer.
cost: In py-cli the command set the `fastmcp` logger to CRITICAL so a failed tool call printed once, and set `PERPLEXITY_LOG_LEVEL` for the run. The first commit attempt failed the hook: two tests in `tests/test_log_setup.py` saw no `fastmcp` log output because the level change outlived the call, in a different test file that never mentions the CLI. It cost a failed full-suite run (about 100 s) and a re-commit.
enforced_in: `command.run_tool` restores the logger level and the environment variable in `finally` (tests in `tests/test_command_run.py` run the command in-process), and the commit hook runs the whole suite on the staged tree, which is what found it.
---

A function that changes process-global state for its own duration restores it in `finally`, even
when a CLI would exit right after, because tests call the same function in-process and share the
interpreter. Prefer passing the setting in (a parameter) over changing the global. When a change
touches logging, environment or signals, run the whole suite before the first commit, not only the
new test file.

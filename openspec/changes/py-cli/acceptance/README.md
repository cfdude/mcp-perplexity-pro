# Acceptance record, py-cli (2026-10-13/14)

Run with `uv run perplexity-pro ...` from the repository, the real key (read from the gitignored ecosystem file into the environment, never printed) and a temporary data directory, so the live server's database is untouched. The server (pm2) is not involved: the CLI calls the tools in-process.

- `help-top.txt`, `help-index.txt`, `help-ask.txt`, `ask-help.txt`: `--help`, `help`, `help ask` and `ask --help` (exit 0).
- `models-json.txt`: `models --json | jq`: 52 models and the routing section (standard, `perplexity/sonar`, `known` true).
- `ask-text.txt` and `ask.json`: the same question asked twice on project `acceptance-cli`, in text (the answer, a source list and the usage line) and with `--json` (structured result: `routing.selected_by` `default`, model `perplexity/sonar`, cost `0.00359`, reported). Both exit 0, standard error empty.
- `refused.err`: `ask q --depth high` exits 1 with `[invalid_request] depth: ... use perplexity_research. Run perplexity-pro help ask for its arguments and examples.` (the CLI form of the help sentence), standard output empty, nothing sent.
- `usage.json`: `usage --project acceptance-cli --json`: 2 calls, 0.00723 USD. The two ask results cost 0.00364 (text) and 0.00359 (JSON), which sum to the ledger's 0.00723 to the nano-USD.
- `delete.txt`: `projects delete --project acceptance-cli --confirm` removed the project (spend history kept). Total spend 0.00723 USD, 2 billed calls.

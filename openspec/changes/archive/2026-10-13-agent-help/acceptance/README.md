# Acceptance record, agent-help (2026-10-13/14)

Live server: pm2 app `mcp-perplexity-pro` on 8102, restarted with `pm2 restart ecosystem.config.cjs --update-env` (the lesson `restart-pm2-from-the-ecosystem-file`), branch `epic/agent-help`. An authenticated call (`perplexity_models`) succeeded before anything else counted. No spend.

- `tools-list.json`: `tools/list`, eleven tools, 55512 bytes measured with `wc -c` on one POST. Against 59779 after the routing change that is 4267 bytes smaller (7.1%), and 1386 smaller than the 56898 before the routing change. The reduction comes from removing the `title` annotations pydantic writes on every schema node (design D8); the help tool itself is included.
- `help-index.json`: the index, 871 bytes of ASCII (cap 1500).
- `help-tool-search.json`, `help-topic-routing.json`: one tool page and one topic.
- `invalid-ask-hint.json`: `perplexity_ask` with depth `turbo` fails `invalid_request` and the message ends with the sentence naming `perplexity_help` and `perplexity_ask`.
- `help-unknown-tool.json`: help's own refusal lists the valid names and has no extra hint.
- `perplexity_usage` totals: 40 calls before the help calls and 40 after (no usage event, no project).

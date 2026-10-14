# Acceptance record, routing-modes-config (2026-10-13/14)

Live server: pm2 app `mcp-perplexity-pro` on 8102, branch `epic/routing-modes-config-impl`, standard mode with defaults.

- `initialize.json`: the `instructions` text the server returns (standard mode, `perplexity/sonar`).
- `tools-list.json`: `tools/list`; ten tools; measured with `wc -c` on one `tools/list` POST. Size and comparison are in the 5.1 line of `tasks.md`.
- `models-routing.json`: `perplexity_models` `routing` section, standard model `known` true.
- `probe-chat-model-switch.md`: a chained chat turn can switch models (design D8b).

Incident: the first `pm2 restart --update-env` took the shell's `PERPLEXITY_API_KEY`, which differs from the one in the gitignored `ecosystem.config.cjs`, so every upstream call returned `authentication`. `pm2 restart ecosystem.config.cjs --update-env` restored the file's key (verified by comparing a hash of the process's key with the file's, never printing it). Lesson: restart this app from its ecosystem file.

## Results

**5.1.** `/health` ok; `initialize` carries the standard-mode instructions; `tools/list` lists ten tools, 59779 bytes against 56898 before this change: +2881 bytes, +5.1%. That is over the 3% target of design D5. The growth is the `tier` argument and `routing` result field on two tools, the routing section of `perplexity_models` and the mode sentence in two descriptions; the registered `agent-help` epic trims descriptions. `perplexity_models` shows the routing section with `perplexity/sonar` `known` true.

**5.2.** Billed calls on throwaway project `acceptance-routing` (raw output in `billed-calls.json`): the default instance (standard mode) answered a default ask on `perplexity/sonar` (`selected_by` default, $0.00336), a `depth` fast ask on `openai/gpt-6-luna` ($0.00124), an explicit `model` ask ($0.00304) and a `json_schema` ask on the default Sonar route (parsed `answer_json`, $0.00371); a `tier` call and a depth+model call were refused with the teaching messages and cost nothing. A second instance (custom mode; tiers `openai/gpt-6-luna`, `perplexity/sonar`, `anthropic/claude-sonnet-5-5`, ephemeral port, own data directory) answered one ask per tier and one default ask (`selected_by` tier and default), a chat turn with `tier` light then a chained turn with `tier` complex (model switch through the new code), and refused a tier+model call. `perplexity_usage` reconciles to the results' `cost_usd` to the nano-USD on both instances: $0.01135 for 4 calls (default instance) and $0.0064 for 6 calls (custom instance), $0.01775 in total. Both projects were deleted afterwards.

Measured, one sample each: a default Sonar ask cost $0.00336 and the `fast` preset $0.00124 for the same question (2.7 times); on the custom instance the three tiers cost $0.00005 (luna), $0.00013 (Sonar, short question) and $0.00297 (Claude Sonnet 5.5).

Not run: the medium research marker check. `perplexity_research` is unaffected by routing (it always names a preset), so that check has no routing path to prove; the citation-marker rules already have their own acceptance record (`py-agent-citation-fixes`), and the Sonar answer above carries `[[1], [2], ...]` markers that match the `ids` of its sources.

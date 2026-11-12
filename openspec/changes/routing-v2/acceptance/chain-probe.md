# Chained turn that switches models (routing-v2 task 1.4), 2026-11-11

Throwaway script outside the repo (scratch data directory, no pm2). Bodies in `chain-probe/`
(request and response, no keys). Earlier evidence: 2026-10-13 `perplexity/sonar` then `openai/gpt-6-luna`
through the running server, both completed, second `continuation` `chained`
(`openspec/changes/archive/2026-10-13-routing-modes-config/design.md` D8b). Repeated here on the shortlist
models, with `store` false on every turn (the house chain):

| Turn | Request | Result |
|---|---|---|
| 1 | `openai/gpt-6-luna`: "Remember the word PAPAYA. Reply with OK." | 200 `completed`, `model` `openai/gpt-6-luna`, 0.00001 USD |
| 2 | `anthropic/claude-haiku-5-5` (+ `max_output_tokens` 200), `previous_response_id` of turn 1: "What word did I ask you to remember?" | 200 `completed`, `model` `anthropic/claude-haiku-5-5`, answer `PAPAYA`, 0.00001 USD |
| 3 | back on `openai/gpt-6-luna`, `previous_response_id` of turn 2: "And what was the word again?" | 200 `completed`, `model` `openai/gpt-6-luna`, answer `PAPAYA`, 0.00002 USD |

Findings:
- A chained turn on a DIFFERENT model works in both directions (OpenAI to Anthropic and back) and carries the
  context, including from a `store` false turn. The held-model rule of design D12 and the router's re-route
  after a removed model can rely on it: switching never breaks a chain.
- The `model` a routed turn reports is exactly the id that was requested, on every turn (no alias, no
  version suffix, unlike a preset call, which reports the resolved model with a versioned `preset`).
- The response does not echo `previous_response_id` (it is `null` in each body), and `reasoning` is `null`
  when no `reasoning` was sent. A chain needs the caller's own record of the previous id, which chat storage
  already keeps.

Spend: about 0.00004 USD.

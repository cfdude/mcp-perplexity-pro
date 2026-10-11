# Proposal

## Why

The server can answer questions and return raw search results, but cannot ask Perplexity's Decisions API (`POST /v1/decisions`) to classify, grade or rate a piece of text. The API returns a calibrated probability for each question you put to a text, at $0.02 per million input tokens (a typical call costs a few thousandths of a cent), with no LLM answer to read: a yes/no probability (`noul`), a pick from a list with each option's probability (`choice`), or a position on an ordered rubric (`score`). A coding agent uses it to triage, route and gate cheaply. It is also the building block the later routing epics (`routing-decisions-classifier`) depend on. This change adds one tool, `perplexity_decide`, and makes its spend visible: it is the fourth producer of usage events (second whose cost the API does not report, computed from input tokens).

The Decisions API was probed live on 2026-10-11 (19 billed or refused requests; 17 captures committed as `tests/fixtures/decisions_*.json` in `8203c1e` and 2 more, the 11 and 32 question requests, in `d096659`). The probe settled things the documentation leaves open: the response has no request id in its body (only an `x-request-id` header), and `usage` has token counts and no cost; an empty-string `state` is accepted and billed; a missing or unknown `model` is a 400 whose message names the model; a wrong question `type` and an unknown top-level field share one generic 400 message; the 128-question maximum is enforced (129 gives 400) and 32 questions in one request was a 200; the provider rate limit is 10 requests per second, counted per request, not per question. See `design.md` "Observed shapes".

## What Changes

- Add one tool, `perplexity_decide`: `state` (text, or a JSON object or list describing the situation; no images), `questions` (a mapping from a name the caller chooses to a question of type `noul`, `choice` or `score`), an optional `model` (`pplx-decider-v1.1-27b` by default, or `pplx-decider-v1-27b`) and `project`. The result holds one typed answer per question (probability for `noul`; chosen option, confidence and every option's probability for `choice`; weighted score, confidence, legend and probabilities for `score`), the input and output token counts, the exact decimal USD cost with its source, the latency, the project and warnings.
- Everything the probe showed the API accepts wrongly or reports vaguely is validated locally before any call: at most 32 questions (this server's own cap; the API allows 128), non-blank names, `noul` needs criteria or instructions, `choice` needs 1 to 255 options, `score` 1 to 10 levels, a blank `state` is refused (the API accepts and bills it), and image content in `state` is refused (not supported in v1).
- Add `PerplexityClient.decide(body)` and a tolerant response model (`answers` and `usage` kept as received; only a missing `answers` object is `unexpected_response`); a Decisions POST is never replayed after a response other than 429.
- Record exactly one usage event per Decisions request that reaches the API through the shared `costed.costed_call`: API family `decisions`, tool `perplexity_decide`, the response `model`, the token counts, cost computed by `pricing.decisions_cost_nano(input_tokens)` (output tokens are free), and a null request id (the body has none). A response whose token counts cannot be read is recorded with cost unknown, not zero.
- Out of scope: images in `state` (the API accepts base64 data URLs; v1 refuses them), caching of answers, streaming, a batch tool, retries beyond the client's existing rules, a cost ceiling, auto-routing (the `routing-*` epics).

## Capabilities

### New Capabilities

- `decisions-client`: typed access to the Decisions API in the client: the `decide` call, tolerant response models, retry rules for a billed POST, error mapping, diagnostics.
- `decisions-tool`: the `perplexity_decide` tool: arguments and local validation, request building, the answer shape, the per-request cost and its recording.

### Modified Capabilities

None. Checked against the main specs: `usage-recording` already names API family `decisions`, the computed-cost rule and the one-event-per-call contract; `perplexity-client` states the create-POST retry rule for any POST; `server-runtime` "Secrets are never emitted" needs no change because the answers hold only numbers and the caller's own option names and legend text (the configured key is still scrubbed from every string).

## Impact

- **Code:** `src/mcp_perplexity_pro/` gains `models/decisions.py`, `decisions.py` (validation, request building, digestion, `decisions_usage`, `run_decide`), `tools/decisions.py`; `client.py` gains `decide`; `tools/__init__.py` registers one tool (nine in total). `decisions.py` imports `_bad`, `check_text`, `_int_in` from `agent.py` and `costed_call` from `costed.py`. `usage.py`, `pricing.py` and `errors.py` change nothing.
- **Tests (existing files edited):** `tests/test_server.py` and `tests/test_contract_checks.py` (the sorted tool list, its test name; the `costed_call` caller sweep gains `decisions.run_decide`; the category and secrets checks gain the tool), `tests/test_recording_order.py` (a decide case), `tests/test_wiring_one_event_per_call.py` (a decide call, the totals and by-api groups).
- **Specs:** two new capabilities, no modified requirement.
- **Dependencies, settings, migrations:** none.
- **Spend:** a few thousandths of a cent per call (a 347-token request costs 6940 nano-USD); nothing local caps the number of calls (the provider limit seen is 10 requests per second). The live acceptance spends under $0.001.
- **Tool surface:** from eight tools to nine, the design target of CLAUDE.md. `tools/list` was 45542 bytes with eight; the growth is measured and recorded in `design.md` Risks. The input schema of `questions` is kept to a loose object so it does not balloon.
- **Risks carried forward:** the cost is always computed (the API reports none); a billed 200 with unreadable usage is recorded with cost unknown; the answers are model output (probabilities), not facts, and the description says so.

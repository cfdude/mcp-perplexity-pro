# Request shape probe (routing-v2 task 1.1), 2026-11-11

Throwaway script outside the repo, then the capture test `test_capture_routing_request_shape_fixtures`
in `tests/test_live_capture.py` (fixtures `agent_model_effort_web_search`, `agent_opus55_medium_web_search`,
pinned by `tests/test_routing_probe_fixtures.py`). Scratch data directory, no pm2, no port 8102. The key was
read from the environment only.

## Shape that works

`POST /v1/agent` with `model`, `input`, `store` false, `reasoning: {"effort": "<level>"}`,
`tools: [{"type": "web_search"}]`, `max_steps` 3. Anthropic models also need `max_output_tokens`
(known, `agent_anthropic_no_max_output_tokens_400`).

| Probe | Result |
|---|---|
| `openai/gpt-6-luna`, `low`, web search, max_steps 3 | 200, status `completed`; response `reasoning` = `{"effort": "low", "summary": null}`; response `effort` and `preset` null (a model-named call has neither); 1 search call at 0.0025 USD |
| `anthropic/claude-opus-5-5`, `medium`, web search, max_steps 3, `max_output_tokens` 1500 | 200, `completed`; `reasoning` = `{"effort": "medium", "summary": null}`; 1 search call |
| a call that sends no `reasoning` | response `reasoning` is `null` (chat probe 1.4) |

Accepted levels: the 2026-10-17 matrix baseline records `minimal`, `low`, `medium`, `high`, `xhigh`, `max`
accepted for both models; this probe re-confirmed `low` (luna) and `medium` (opus-5-5) live. The API's own
validation message lists the full vocabulary: `effort must be one of: none minimal low medium high xhigh max`
(note `none`, which the matrix does not probe; see 1.5).

## Figures for the pilot (7.1b) and the evaluation caps (first run, per request)

| Model, level | input tokens (cache created / read) | output tokens | search calls | cost USD | latency |
|---|---|---|---|---|---|
| `openai/gpt-6-luna`, `low` | 4869 (4379 / 0) | 94 | 1 | 0.00315 | 3.6 s |
| `anthropic/claude-opus-5-5`, `medium` | 7845 (6681 / 1156) | 217 | 1 | 0.04051 | 6.1 s |

The throwaway run of the same two requests measured 0.00312 and 0.03421 USD (3.5 s, 5.1 s): the cost of the
Opus request varies by about 20 percent between runs with the cache state (the search call itself is a flat
0.0025 USD). Most of each bill is prompt-cache creation: the web search tool injects about 4k to 6k input
tokens, so a search-enabled call costs far more than the prompt suggests (a 94-token answer cost 0.003 USD on
the cheapest model).

Spend of this probe family: about 0.08 USD (throwaway 0.037 plus capture 0.044).

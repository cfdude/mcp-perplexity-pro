# What the API answers for a retired model and for an effort refusal (routing-v2 task 1.5), 2026-11-11

Throwaway script outside the repo (scratch data directory, no pm2, no port 8102), then the capture test
`test_capture_model_gone_fixtures` (fixtures `agent_model_not_served_400`, `agent_effort_refused_400`; the unknown
poll fixture `agent_get_unknown_404` already exists), all pinned by `tests/test_routing_probe_fixtures.py`. Raw
request and response of every probe: `model-gone-probe/`.

## (a) A model the API does not serve

| Request | Status | Body |
|---|---|---|
| `openai/gpt-99-luna` (real stem, version nobody serves) | 400 | `validation failed: model "openai/gpt-99-luna" is not supported` (`type` `invalid_request`, `code` 400), 0.16 s |
| `anthropic/claude-haiku-99` | 400 | `validation failed: model "anthropic/claude-haiku-99" is not supported`, 0.17 s |
| `perplexity/nemotron-3-ultra-550b-a55b`: in the 2026-10-30 baseline, ABSENT from today's live `/v1/models` listing (the one removed id: the listing has 56 models, 54 in the baseline, nemotron gone, `anthropic/claude-fable-5-2`, `google/gemini-4-carbon`, `openai/gpt-6.1-terra` new) | 400 | the same text, 0.16 s |
| `GET /v1/agent/resp_00000000-...` (an unknown response id) | 404 | `resource not found` (`type` `not_found`), 0.20 s: names no model |

- A 404 or a 410 never appeared for a model: only the 400 above. So `matrix.model_not_served` (media-inputs 2.1)
  needs no amendment: true for that 400, and for a 404/410 only when the message names the requested model (none
  observed, kept as the spec's defensive rule). The poll's 404 does not match it (no model named).
- None of the three bodies has a `usage` block or a response `id`: no run was created. The ASSUMPTION that a
  not-served 400 is unbilled is supported by that and by the 0.16 s latency, but it is not verified against the
  account ledger (the API offers no balance or usage read; the server's own usage log records only what it sends).
  Recorded as an inference, not a measurement.

## (b) An effort refusal

| Request | Status | Body |
|---|---|---|
| `openai/gpt-5-nano`, `reasoning.effort` `xhigh` (matrix: refused) | 400 | `invalid request` (`type` `invalid_request`, `code` 400), 0.9 s |
| `openai/gpt-5-nano`, `max` | 400 | `invalid request`, 0.8 s |
| `google/gemini-3.1-pro-preview`, `minimal` (matrix: refused) | 400 | `invalid request`, 0.7 s |
| `perplexity/deepseek-v4-pro-0813`, `low` (matrix: every level refused) | 400 | `invalid request`, 0.7 s |
| `openai/gpt-6-luna`, `turbo` (a level nobody has) | 400 | `validation failed: effort must be one of: none minimal low medium high xhigh max`, 0.16 s |

- The refusal of a level a model does not support is ONLY the generic `invalid request`: nothing in the body says
  it is the level. The captured-text branch of `matrix.is_effort_refusal` therefore does not exist; the FALLBACK
  RULE of design D17 applies (a 400 whose message is the generic `invalid request`, on a request that carried
  `reasoning`, that is not a not-served answer and not a named modality refusal). Design D17 now says so.
- The two classifiers are disjoint on the captured texts: the effort body does not satisfy `model_not_served`,
  and the not-served body is not the generic text.
- The API's own vocabulary includes `none` (`fast` runs at `none`): the matrix does not probe it. Not acted on.

Spend: 0 USD that the API reports: every request in this family was a 400 with no usage block (the validation
and refusal answers are not billed on what is observable).

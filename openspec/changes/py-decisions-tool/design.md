## Context

The Search change (`openspec/changes/archive/2026-10-11-py-search-api/`) added `costed.costed_call` as the one generic costed-call sequence and the pattern of a computed cost. Decisions is the same shape (one POST, a JSON answer, a computed cost) and reuses all of it. What differs: the request is a structured question set rather than a query, the response carries token counts, and nothing in the response body identifies the request.

## Goals / Non-Goals

**Goals:** one tool `perplexity_decide`; local validation of everything the probe showed the API reports vaguely or bills for nothing; exact per-request cost from input tokens; exactly one usage event per request; no new setting, no migration.

**Non-Goals:** images (v1 refuses them), caching, batching, routing (the `routing-*` epics), a cost ceiling, per-question cost attribution (one request is one cost), reading `x-request-id` (the client exposes no headers; see D5).

## Decisions

**D1. One tool, two new modules.** `models/decisions.py` (`DecisionsResponse`), `decisions.py` (`DecideOptions`, `build_request`, `digest`, `decisions_usage`, `run_decide`), `tools/decisions.py`. The tool name is `perplexity_decide` (a verb like `ask`, `search`). Annotations: `readOnlyHint` false (it writes a usage event and may create a project), `destructiveHint` false, `openWorldHint` true (an external API), like the other costed tools.

**D2. Request building is one pure function `build_request(options)`.** Rules and the probe evidence behind each:

| Rule | Evidence |
|---|---|
| `model` is `pplx-decider-v1.1-27b` (default) or `pplx-decider-v1-27b`, ALWAYS sent | `decisions_missing_model_400` (`Invalid model ''`), `decisions_unknown_model_400`; both models answered (`decisions_noul`, `decisions_model_v1`) |
| `questions` is a non-empty mapping, at most 32 entries (our own cap), each name a non-blank string of at most 128 characters (our own cap) | `decisions_empty_questions_400` and `decisions_129_questions_400` (`Each request needs between 1 and 128 questions`), `decisions_empty_question_name_400` (`Question key cannot be empty`); 11 and 32 questions were 200s (`decisions_11_questions`, `decisions_32_questions`); a larger count is allowed by the API up to 128, the lower cap bounds one call's response size and input tokens |
| a question `type` is `noul`, `choice` or `score` | `decisions_bad_type_400` (the generic message `The request body is not valid JSON for the Decisions API, or has an unknown or mistyped field.`, shared with an unknown top-level field, `decisions_unknown_field_400`) |
| `noul` needs `criteria` (keys `true` and `false`) or `instructions` | `decisions_noul_no_criteria_400` (`Noul question must have criteria or instructions`) |
| `choice` needs `criteria`, a mapping of 1 to 255 options (an option's description may be null) | `decisions_choice_no_options_400` (`Each decision needs between 1 and 255 options`) |
| `score` needs `criteria`, a list of 1 to 10 levels (two or more recommended) | `decisions_score_11_levels_400` (`Too many score levels. Must have at most 10 levels.`) |
| `instructions` is optional text, an object or a list; only text, mappings and lists of JSON values are sent | OpenAPI `DecisionsRequest` (documentation); live use of text only |
| `state` is non-blank text, or a JSON object or list (not empty); its serialized size is at most 200000 characters (our own cap; the API limit is 262144 tokens) | `decisions_empty_state` is a billed 200 with no content, so a blank state is refused locally |
| image content in `state` is refused: any `image_url` key, or a string starting `data:image/` | v1 non-goal; the API accepts base64 data URLs in an array |
| nothing else is sent; an unknown option cannot be passed | an unknown top-level field is a 400 |

**How the request tests compare.** Each recorded request the tool accepts is rebuilt from the options that produce it and compared with the sidecar's `request` exactly. The recorded 200 requests that are not reproduced are named by the test (`decisions_empty_state`: refused locally; the 400 requests are rebuilt only where the local rule agrees, and otherwise asserted refused).

**D3. Digestion is one function** (`digest(response, secrets, *, question_names)`, never raises). For each question name in the caller's order, the answer is read from `answers`: a mapping with a string `type` of `noul`, `choice` or `score` and numeric fields becomes a `DecisionAnswer` (`type`, `noul`, `choice`, `confidence`, `probabilities`, `score`, `legend`; fields that do not apply are null). A missing answer, a non-mapping answer or an unknown type gives no answer for that name and one warning naming it; the call is not failed (it is billed). Strings from the API (`choice`, the `legend` values, probability keys) are those the caller supplied in `criteria`, and the configured key is replaced by `[redacted]` in them anyway (`scrub_secrets`), then capped at 500 characters. Numbers that are not finite floats become null. `usage` token counts are read only when they are non-negative ints.

**D4. Cost is computed, always.** The response has `usage.input_tokens` and `usage.output_tokens` and no cost (in all 8 committed 200 responses). `decisions_usage(raw)` returns `computed_usage(pricing.decisions_cost_nano(input_tokens), input_tokens=..., output_tokens=..., total_tokens=input+output, input_cost_nano=<cost>, raw=<usage when a dict>)` (output tokens are free, no per-request fee), source `computed`. When `input_tokens` is not a non-negative int the cost cannot be computed: `Usage(raw=...)` with source `none` (unknown, not free), and the result's `cost_usd` is null. Evidence: 347 input tokens at 20 nano-USD each is 6940 nano-USD (`"0.00000694"`). Both documented models cost the same.

**D5. Recording and the request id.** `run_decide` calls `costed_call` (the same order as every other tool). The event: tool `perplexity_decide`, API `decisions`, model from the response `model` when a string (the echoed request model otherwise), no preset, request id null: the response body has no id and the client exposes no headers (the Search design reached the same limit and used the body id). The dedupe index `uq_usage_events_api_request_id` does not constrain rows whose request id is null, so identical repeated requests each record an event, which is correct: each was billed.

**D6. Client.** `PerplexityClient.decide(body)` is `POST /v1/decisions` through `request_json` (no timeout override: the probe saw 0.27 to 0.68 s; the documentation says a 504 after about a minute, which is `upstream_failure` and never replayed), parsed with `_parse` into `DecisionsResponse`: `answers: dict[str, Any]` required, `model: Any`, `usage: Any`, `extra="allow"`. A missing or non-object `answers` is `unexpected_response` naming `/v1/decisions` and `answers`. A path with a trailing slash returns 404 (documented), so the path is exactly `/v1/decisions`.

**D7. Errors.** Every validation failure observed is HTTP 400 `{"error": {"message", "type", "code"}}` (`invalid_request` or `invalid_request_error`), 401 `invalid_api_key`; the existing mapping by status handles all of it and the API's message passes through redacted. The 429 body of this API was not captured; the generic status mapping and `Retry-After` apply.

**D8. Output.** `DecideOutput`: `answers` (a mapping from the caller's name to its `DecisionAnswer`, in the caller's order), `model`, `input_tokens`, `output_tokens`, `cost_usd`, `cost_source`, `latency_ms`, `project`, `warnings`. Text content is one line per question and a usage line. Money is the exact string.

**D9. Context cost of a ninth tool.** `tools/list` was 45542 bytes with eight tools (`perplexity_search` alone 5066). The `questions` parameter is typed as an object with free-form values and its schema description carries the three question shapes in prose; measured and recorded in group 3. The CLAUDE.md design target is about nine tools; this is the last planned tool before embeddings (a tenth would exceed the target: embeddings needs one tool, not two, or a trimmed set).

**D10. Tests.** Offline through `build_server` with a `MockTransport` serving the recorded fixtures, a request-capturing transport for exact bodies, the mutation-check rule for the recording order and for the blank-state and image refusals. Lessons applied: `redaction-patterns-need-identifier-regressions` (a `pplx-decider-v1.1-27b` model id in a choice must survive), `best-effort-writers-and-the-callers-write-lock`, `framework-logs-carry-bound-parameters` (the state, the questions and the answers never reach a log). The usage dedupe index is not a hazard here (null request id).

## Risks / Trade-offs

- **Cost is computed, never reported** (D4) -> `cost_source` says `computed`; token counts come from the response. The acceptance reconciles the server's books to the nano-USD and cannot check the provider's bill (the console was not read for Search either).
- **The answers are probabilities from a model, not facts** -> the description says so; the tool adds no threshold.
- **No request id** (D5) -> events cannot be matched to the provider's logs; accepted.
- **32-question and 128-character-name caps are our own** (D2) -> labelled in the spec; raising them is a constant.
- **Rate limit 10 requests per second** (probe) -> a 429 maps to `rate_limited`; one request is one unit regardless of its question count.
- **A 504 may be HTML** (documentation) -> the existing non-JSON handling maps it to `upstream_failure`.
- **The tool surface grows from 8 to 9** (D9) -> measured in group 3.
- **Image refusal is a heuristic** (D2) -> a `data:image/` prefix or an `image_url` key; an image smuggled in another shape would be sent to the API as text and billed; acceptable.

## Migration Plan

No migration, no setting. pm2 restart reloads the tool list.

## Open Questions

None. The `x-request-id` header could be exposed by the client later (a client change touching every tool) and is not needed now.

## Observed shapes (the evidence for the decisions above)

Live probe 2026-10-11, key never recorded. 200 responses: `{"model", "answers": {<name>: {...}}, "usage": {"input_tokens", "output_tokens"}}`, no `id`, no cost. Latencies 0.27 to 0.68 s. Headers: `x-request-id`, `x-ratelimit-limit` 10, `x-ratelimit-used` counting requests.

| Fixture | Request | Result |
|---|---|---|
| `decisions_noul` | one noul, text state | 200, `noul` 0.988, 104 input tokens |
| `decisions_choice` | choice with a null option description | 200, `choice` `software`, confidence, three probabilities, 115 tokens |
| `decisions_score` | four levels | 200, `score` 1.70, confidence, `legend` and `probabilities` keyed `"0"` to `"3"`, 107 tokens |
| `decisions_three_questions` | noul, choice, score; object state | 200, three typed answers, 347 tokens, 3 output tokens |
| `decisions_model_v1` | `pplx-decider-v1-27b` | 200, `model` echoed |
| `decisions_empty_state` | state `""` | 200 (billed, 82 tokens) |
| `decisions_11_questions`, `decisions_32_questions` | 11 and 32 noul questions | 200 |
| `decisions_missing_model_400` | no model | 400 `Invalid model ''` |
| `decisions_unknown_model_400` | `pplx-decider-nope` | 400 `Invalid model 'pplx-decider-nope'` |
| `decisions_unknown_field_400`, `decisions_bad_type_400` | `bogus` field; type `rank` | 400, the same generic message |
| `decisions_empty_questions_400`, `decisions_129_questions_400` | 0 and 129 questions | 400 `Each request needs between 1 and 128 questions` |
| `decisions_noul_no_criteria_400` | noul with nothing | 400 `Noul question must have criteria or instructions` |
| `decisions_choice_no_options_400` | empty criteria | 400 `Each decision needs between 1 and 255 options` |
| `decisions_score_11_levels_400` | 11 levels | 400 `Too many score levels. Must have at most 10 levels.` |
| `decisions_empty_question_name_400` | name `""` | 400 `Question key cannot be empty` |
| `decisions_unauthenticated_401` | bad key | 401 `invalid_api_key`, no `x-request-id` |

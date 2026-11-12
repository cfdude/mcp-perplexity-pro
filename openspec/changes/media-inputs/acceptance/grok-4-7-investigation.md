# xai/grok-4.7 media investigation (2026-11-11)

Question: the 2026-10-30 sweep (`sweep.json`, `probe.md`) recorded `xai/grok-4.7` as refusing both
image and document input. Why, and what is the model for?

## 1. What the sweep recorded

| Model | image (48x48 PNG, data URI) | document (one-line PDF, `file_data`) |
|---|---|---|
| `xai/grok-4.7` | 400 `invalid request` | 400 `the selected model route does not support this document type or source` |
| `xai/grok-4.3`, `xai/grok-4.20-reasoning`, `xai/grok-4.20-multi-agent` | same two 400s | same |
| `xai/grok-4.5`, `xai/grok-4.6`, `xai/grok-4.20-non-reasoning` | accepted | accepted |

Classification of the two error bodies:

- Image 400 `invalid request` (type `invalid_request`, code 400) is the GENERIC body. The same body is
  returned for a model that cannot read images (`captures/G_image_deepseek-v4-.json`). It is neither
  a named modality refusal nor the `validation failed: model ... is not supported` unknown-model case.
- Document 400 `the selected model route does not support this document type or source` is a named
  route-level refusal, the same text for every refused xAI model.
- Not a shape bug: the sweep sent the identical `input_image` / `input_file` shapes that succeeded on
  openai/gpt-6-luna, xai/grok-4.5 and xai/grok-4.6 in the same run.
- Not the "model not supported" case: that text only appeared for `perplexity/nemotron-3-ultra-550b-a55b`.

## 2. Re-probe today (2026-11-11), same request shape as `build_request`

`input` = one user message of `input_text` + `input_image` (`image_url` data URI) or `input_file`
(`filename`, `file_data`), `store` false, `max_output_tokens` 150. Tiny PNG generated with Python stdlib.

| Model | kind | HTTP / status | answer | latency | cost USD | input tokens |
|---|---|---|---|---|---|---|
| xai/grok-4.7 | text control | 200 completed | OK | 2.3 s | 0.00116 | 1266 |
| xai/grok-4.7 | image 16x16 | 429 overloaded (x3) | - | ~1.8 s | - | - |
| xai/grok-4.7 | image 48x48 (the sweep's exact image) | 200 completed | Red. | 2.4 s | 0.00008 | 36 |
| xai/grok-4.7 | image 64x64 blue | 200 completed | Blue. | 2.8 s | 0.00008 | 36 |
| xai/grok-4.7 | txt, data URI | 200 completed | PAPAYA | 2.3 s | 0.00009 | 39 |
| xai/grok-4.7 | txt, plain base64 | 200 completed | PAPAYA | 4.8 s | 0.00008 | 35 |
| xai/grok-4.7 | PDF (the sweep's exact PDF) | 200 completed | MANGO | 2.8 s | 0.00011 | 48 |
| xai/grok-4.6 | text / image 64 / txt | 200 / 200 Blue / 200 PAPAYA | | 6.0 / 6.9 / 6.1 s | 0.00006 / 0.00008 / 0.00009 | |
| xai/grok-4.6 | image 16x16 | 429 overloaded (x3) | | | | |
| xai/grok-4.5 | text / image 64 / txt | 200 / 200 Blue / 200 PAPAYA | | 2.6 / 4.5 / 7.2 s | 0.00006 / 0.00008 / 0.00009 | |
| xai/grok-4.5 | image 16x16 | 429 overloaded (x3) | | | | |
| xai/grok-4.3 | text control | 200 completed | OK. | 4.3 s | 0.00061 | 216 |
| xai/grok-4.3 | image / PDF / txt | 400 `invalid request` / 400 route-does-not-support (x2) | | <1 s | - | - |
| xai/grok-4.20-reasoning, -multi-agent | image / PDF / txt | 400 / 400 / 400 (same texts as above) | | <1 s | - | - |
| xai/grok-4.20-non-reasoning | image 64 | 200 Blue | | 1.4 s | 0.00005 | 47 |
| openai/gpt-6-luna | text / image 16x16 / txt | 200 OK / 200 Red / 200 PAPAYA | | 1.8 / 2.4 / 2.0 s | 0 / 0.00001 / 0.00002 | |

Total spend of all probes this session: about $0.0035 (well under the $0.30 budget).
No shape variants (`detail`, https URL, prefix-less base64 for images) were tried: the first error did
not suggest a shape issue, and the plain image succeeded on the retry.

Findings:

- Same payloads that were refused on 2026-10-30 are accepted now by grok-4.7: 48x48 PNG -> "Red.",
  PDF -> "MANGO". So the sweep row is not reproducible today.
- A 16x16 image gets 429 `upstream model is overloaded` on EVERY xAI image-capable model (4.5, 4.6, 4.7,
  4.20-non-reasoning) while 48x48 and 64x64 succeed. Cause not proven; the consistent size dependence
  suggests an upstream minimum-image-size check surfaced as a misleading 429. Unknown.
- grok-4.3 and grok-4.20-reasoning / -multi-agent still refuse today with the sweep's exact texts, while
  being callable with text. So those are consistently text-only routes on Perplexity.
- grok-4.7 text control costs $0.00116 for 1266 input tokens versus 24 for grok-4.6/4.5: a larger
  fixed input overhead for this prompt on 4.7 (cause unknown; not investigated).

## 3. What xAI documents (web search 2026-11-11; not independently opened)

- Official xAI model page lists text and image input, text output, 500,000-token context, reasoning
  effort low/medium/high/xhigh, May 2026 knowledge cutoff, release 2026-09-21; positioned for coding,
  agentic tasks and knowledge work. Sources: https://docs.x.ai/developers/models/grok-4.7 and
  https://docs.x.ai/developers/grok-4-7 (as returned by search), plus
  https://letsdatascience.com/news/xai-releases-grok-47-with-500k-context-43aa2021 and
  https://artificialanalysis.ai/models/grok-4-7.
- Files/audio/video are not listed by xAI for the model (one aggregator, lmmarketcap, claims file input
  and image output; treated as an outlier, unverified).
- The repo's earlier sourced research (`/docs/research/2026-10-15-model-benchmarks/xai.md`) records:
  Vibe Code Bench 86.17% (Vals AI), Terminal-Bench 4.0 28.79% independent / 38.0% xAI-reported,
  Terminal-Bench 2.1 73.41% (Vals AI), Humanity's Last Exam 43.1% (Artificial Analysis); no published
  BrowseComp, MMMU, GPQA or MMLU-Pro found.
- Perplexity changelog (`/docs/research/2026-10-29-api-drift/perplexity-changelog-2026-10-29.md`): "The
  Agent API now supports `xai/grok-4.7`", and it is on the recommended list for new integrations.
- Whether Perplexity's Agent API is documented to pass images for xAI models: not found. Behaviour is
  only known from probes, and it differs per xAI model.
- Pricing: Perplexity `/v1/models` today lists grok-4.7 at 2 / 6 USD per 1M (cache_read 0.5, cache_write 2).

## 4. Verdict

- Not a shape bug on our side, not the unknown-model misclassification. The request shapes are identical
  to those accepted by grok-4.5/4.6 and gpt-6-luna.
- grok-4.7 accepts image and document input on Perplexity's Agent API as of 2026-11-11, matching xAI's
  documented text+image support (documents are a Perplexity-side extraction, not an xAI feature we can
  confirm). The 2026-10-30 refusal was therefore either transient or a route/rollout state on Perplexity's
  side that has since changed (the model was newly added about that time). Which of the two cannot be
  determined from the evidence; the sweep row should be marked stale, not trusted.
- Implication for the matrix: modality must not be baked in from one sweep for xAI. 4.20-reasoning,
  4.20-multi-agent and 4.3 are text-only today; 4.20-non-reasoning, 4.5, 4.6, 4.7 accept both. The same
  model string flipped between runs, so the refusal rule should re-probe a refusal rather than cache it
  permanently, and a generic `invalid request` should stay "unknown" rather than "text-only" when the model
  is new.
- Router role (evidence only): coding and agentic tool use are its strongest published scores (Vibe Code
  Bench, Terminal-Bench), mid-price (2/6 USD per 1M) with a 500K context and an always-on reasoning mode per
  the earlier research. Cheap/strong at browsing: unknown (no BrowseComp found). Reasoning breadth: one HLE
  figure only. Observed latency 2-5 s on tiny calls.
- Not touched: no source, test, pm2 or port 8102. Only this file and scratchpad scripts were written. Nothing committed.

# Live probe results, 2026-10-30

Made with the funded key, through throwaway scripts in `scripts/` (not this server, not the pm2
instance), against `POST https://api.perplexity.ai/v1/agent`. No key was written to a file or
printed. Raw responses are in `captures/` (one JSON per call: `status` and `body`) and the
per-model sweep in `sweep.json`. Response ids are Perplexity's and are not secrets.

Spend: about $0.17 in total before the Gate 1 follow-up probes (below add $0.003) (sweep $0.141 summed from the retained results, single probes
$0.004, one background `medium` run about $0.02 estimated: its queued snapshot carries no usage,
and it was not polled for cost). Budget was $0.50. A first concurrent sweep (6 workers) was
answered with 429 for about half the calls; `x-ratelimit-limit: 3` was seen on a 200 (three
requests per short window), so the sweep was rerun one call at a time. The 429 and
`overloaded` answers cost nothing.

## Request shapes

Every successful call used `input` = `[{"role": "user", "content": [parts]}]` (also with
`"type": "message"` first) and `store` false unless stated. Text part:
`{"type": "input_text", "text": ...}`.

| Probe (`captures/`) | Part | Result |
|---|---|---|
| `A_image_datauri_bare`, `A2_image_message_item` | `{"type":"input_image","image_url":"data:image/png;base64,..."}` on `openai/gpt-6-luna` | 200, answer "Red"; 39 input tokens, $0.00001 |
| `J_image_big_datauri`, `P1_image_over_2048_chars` | data URI of 6544 characters | 200: the OpenAPI `maxLength: 2048` on `image_url` does NOT apply to data URIs (the documentation's 50 MB inline claim holds) |
| `P2_image_wrong_mime` | PNG bytes labelled `image/jpeg` | 200: the API sniffs the bytes |
| `P3_image_svg`, `P4_image_bmp` | SVG and BMP data URIs | 400 `invalid base64 image format. Supported types: jpeg, png, gif, webp` |
| `B_image_https`, `P10_image_https_full` | `image_url` an HTTPS URL | 200, the provider fetched it ("Blue-yellow Python logo beside gray wordmark.") |
| `P5_image_http_url` | `image_url` an `http://` URL | 200 (undocumented leniency for images; documents refuse http, see `P12`; this server refuses http for both) |
| `C_file_b64_pdf`, `C2_file_store_false` | `{"type":"input_file","filename":"doc.pdf","file_data":"<plain base64>"}` | 200, "MANGO" (the PDF's text), with `store` true and with `store` false |
| `D_file_txt_datauri` | `file_data` `data:text/plain;base64,...`, `filename` `note.txt` | 200, "PAPAYA" |
| `E_file_url`, `P11_file_url_full` | `{"type":"input_file","file_url":"https://...pdf"}` | 200, the provider fetched and read it |
| `P12_file_url_http` | `file_url` `http://...` | 400 `file_url must be an HTTPS URL without credentials or fragment` |
| `K_bad_ext`, `P13_file_mislabeled_pdf_as_txt` | `filename` extension does not match the bytes | 400 `filename extension does not match document media type` |
| `L_bad_b64` | `file_data` `!!!notbase64!!!` | 400 `invalid file_data base64` |
| `P14_file_empty` | `file_data` `""` | 400 `file_data must contain between 1 byte and 50 MiB` |
| `N_both` | `file_data` and `file_url` | 400 `input_file requires exactly one of file_data or file_url` |
| `F_audio`, `P17_audio_url_part` | `input_audio` with `data` or `audio_url` | 400 `invalid type "input_audio"` |
| `P16_input_video` | `input_video` | 400 `invalid type "input_video"` |
| `P15_audio_as_file` | a WAV sent as `input_file` | 400 `unsupported document type; use PDF, DOC, DOCX, TXT, or RTF` |
| `P6_two_images_one_doc` | two images and a PDF in one message | 200, "Red blue MANGO" |
| `H_file_with_websearch` | a PDF with `tools:[{"type":"web_search"}]`, `max_steps` 3 | 200 (documentation says browser tools are unavailable with documents; `web_search` was accepted) |
| `I_image_preset_fast` | `effort` `fast`, image part, no model | 200, model `openai/gpt-6-luna`, $0.00175 (6002 input tokens, $0.001 of it the search call) |
| `P19_fast_doc` | `effort` `fast`, PDF | 200, $0.00126 |
| `P19b_low_image`, `P19c_medium_image` | `effort` `low`, `medium`, image | 200 each, $0.00018 and $0.00005 (about 1400 input tokens: the preset's own prompt) |
| `P18_background_research_doc`, `P18b_poll` | `effort` `medium`, `background` true, `store` true, PDF | 200 queued, then `completed` with "MANGO": the API DOES allow research with a document |
| `P7a_doc_store_true`, `P7b_followup_chained` | PDF turn (`store` true), then `previous_response_id` and text only | 200, "MANGO": the file is kept by the continuation |
| `P8a_doc_store_false`, `P8b_followup_after_store_false` | PDF turn with `store` false, then `previous_response_id` | 200, "MANGO": continuation also works from a `store` false turn (the house chain uses `store` false) |
| `P9a_image_store_true`, `P9b_image_followup` | the same for an image | 200, "Red" |
| `P20_chain_adds_new_image` | `previous_response_id` plus a message with a NEW image | 200, "Blue, red": new parts add to the inherited ones |
| `Q_k_doc`, `Q_k_docx`, `Q_k_rtf` (Gate 1 follow-up) | a DOC, a DOCX and an RTF made with macOS `textutil` from one line of text, sent as `input_file` with `filename` `k.doc`, `k.docx`, `k.rtf` | 200 each, "KIWI" (the text), $0.00001 each: DOC, DOCX and RTF are VERIFIED on `openai/gpt-6-luna` |
| `S1_doc_turn`, `S2_text_turn_chained`, `S3_third_turn_chained_asks_doc` | PDF turn, a text-only chained turn, then a chained question about the PDF | 200, "MANGO": the file survives two continuation hops |
| `S4_model_switch_followup` | the same chain, the follow-up on `google/gemini-3.6-flash` | 200, "MANGO": switching models keeps the file ($0.0018) |
| `G_image_deepseek-v4-` | image to a model that cannot read images | 400 body `invalid request` (the generic body) |
| `R_claude-opus-5_file` | a one-line PDF to `anthropic/claude-opus-5` (twice) | 200 with run `status` `failed`, `error` `{"code":"refusal","message":"document processing failed: refusal"}`, no usage: a model refusal, not a type error |
| `R_glm-5.3_file`, `R_glm-5.3-flash_file`, `R_kimi-k3_file` | PDF | 429 `upstream model is overloaded` (no answer; unprobed) |

Not exercised (no probe): the 50 MiB, 30-document and 72 MiB body limits (documented only),
`file_id`, zero-data-retention behaviour, video as a document. Documents verified live: PDF, UTF-8
TXT, DOC, DOCX, RTF (one cheap model each; other models may differ per the sweep). The captures
`I_image_preset_fast.json` and `P19_fast_doc.json` had their search-result items (scraped
third-party text) removed; usage and the message are kept.

## Sweep: which models accept which kind

One image request (a 48 by 48 red PNG, "What colour is this image? One word.") and one document
request (a one-line PDF "The secret word is MANGO", "What is the secret word in the document? One
word.") per model, `max_output_tokens` 150, `store` false. "accepted" means HTTP 200 with a
completed or incomplete run (`openai/gpt-5-mini` and `gpt-5-nano` spent their 150 tokens
reasoning and are still accepted: the probe asks whether the API answers, not whether the answer
is right; every `completed` answer was in fact right).

| Model | Image | Document |
|---|---|---|
| `anthropic/claude-fable-5` | accepted | accepted |
| `anthropic/claude-fable-5-1` | accepted | accepted |
| `anthropic/claude-haiku-4-5` | accepted | accepted |
| `anthropic/claude-haiku-5-5` | accepted | accepted |
| `anthropic/claude-opus-4-5` | accepted | accepted |
| `anthropic/claude-opus-4-6` | accepted | accepted |
| `anthropic/claude-opus-4-7` | accepted | accepted |
| `anthropic/claude-opus-4-8` | accepted | accepted |
| `anthropic/claude-opus-5` | accepted | 200 but run failed: document processing failed: refusal -> unprobed |
| `anthropic/claude-opus-5-5` | accepted | accepted |
| `anthropic/claude-sonnet-4-5` | accepted | accepted |
| `anthropic/claude-sonnet-4-6` | accepted | accepted |
| `anthropic/claude-sonnet-5` | accepted | accepted |
| `anthropic/claude-sonnet-5-5` | accepted | accepted |
| `google/gemini-3-flash-preview` | accepted | accepted |
| `google/gemini-3.1-flash-lite` | accepted | accepted |
| `google/gemini-3.1-pro-preview` | accepted | accepted |
| `google/gemini-3.5-flash` | accepted | accepted |
| `google/gemini-3.5-flash-lite` | accepted | accepted |
| `google/gemini-3.6-flash` | accepted | accepted |
| `google/gemini-3.7-flash` | accepted | accepted |
| `google/gemini-3.8-flash` | accepted | accepted |
| `google/gemini-4-argon` | accepted | accepted |
| `openai/gpt-5` | accepted | accepted |
| `openai/gpt-5-mini` | accepted (incomplete) | accepted |
| `openai/gpt-5-nano` | accepted (incomplete) | accepted (incomplete) |
| `openai/gpt-5.1` | accepted | accepted |
| `openai/gpt-5.2` | accepted | accepted |
| `openai/gpt-5.3-codex` | accepted | accepted |
| `openai/gpt-5.4` | accepted | accepted |
| `openai/gpt-5.4-mini` | accepted | accepted |
| `openai/gpt-5.4-nano` | accepted | accepted |
| `openai/gpt-5.5` | accepted | accepted |
| `openai/gpt-5.6-luna` | accepted | accepted |
| `openai/gpt-5.6-sol` | accepted | accepted |
| `openai/gpt-5.6-terra` | accepted | accepted |
| `openai/gpt-6-astra` | accepted | accepted |
| `openai/gpt-6-luna` | accepted | accepted |
| `openai/gpt-6-sol` | accepted | accepted |
| `openai/gpt-6.1-sol` | accepted | accepted |
| `perplexity/deepseek-v4-pro-0813` | refused 400 `invalid request` | accepted |
| `perplexity/glm-5.3` | refused 400 `invalid request` | 429 upstream model is overloaded, please try again later -> unprobed |
| `perplexity/glm-5.3-flash` | accepted | 429 upstream model is overloaded, please try again later -> unprobed |
| `perplexity/kimi-k3` | accepted | 429 upstream model is overloaded, please try again later -> unprobed |
| `perplexity/nemotron-3-ultra-550b-a55b` | 400 `validation failed: model "perplexity/nemotron-3-ultra-550b-a55b" is no...` -> unprobed (model not served) | 400 `validation failed: model "perplexity/nemotron-3-ultra-550b-a55b" is no...` -> unprobed (model not served) |
| `perplexity/nemotron-3.5-super-120b-a12b` | accepted | refused 400 `invalid request` |
| `perplexity/sonar` | accepted | accepted |
| `xai/grok-4.20-multi-agent` | refused 400 `invalid request` | refused 400 `route does not support this document type or source` |
| `xai/grok-4.20-non-reasoning` | accepted | accepted |
| `xai/grok-4.20-reasoning` | refused 400 `invalid request` | refused 400 `route does not support this document type or source` |
| `xai/grok-4.3` | refused 400 `invalid request` | refused 400 `route does not support this document type or source` |
| `xai/grok-4.5` | accepted | accepted |
| `xai/grok-4.6` | accepted | accepted |
| `xai/grok-4.7` | refused 400 `invalid request` | refused 400 `route does not support this document type or source` |

Counts over the 54 models in the baseline: image accepted 47, refused 6, unprobed 1
(`perplexity/nemotron-3-ultra-550b-a55b`); document accepted 44, refused 5, unprobed 5 (that
model, `anthropic/claude-opus-5`, `perplexity/glm-5.3`, `perplexity/glm-5.3-flash`,
`perplexity/kimi-k3`).

Side finding for the maintainer: `perplexity/nemotron-3-ultra-550b-a55b` is in `/v1/models` and in
the baseline as `available`, but the Agent API answers any request for it with `400 validation
failed: model \"perplexity/nemotron-3-ultra-550b-a55b\" is not supported`, also for a plain text
input (checked 2026-10-30). It is not an attachment issue, and the matrix has no way to say "listed but not servable".

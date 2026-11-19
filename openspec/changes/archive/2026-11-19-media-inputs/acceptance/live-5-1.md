# Live acceptance, task 5.1 (2026-11-19)

Run of `acceptance/scripts/live_5_1.py` at commit `3065ad4` of branch `epic/media-inputs`, through
the `perplexity-pro` command, with a temporary data directory and a real key from the environment
(never printed; every saved output went through `redact_text`). Outputs: `acceptance/live-5-1/`
(one JSON per step, `d_reconciliation.txt`, `e_models_inputs.txt`, `f2_http.json`).

Spend (the sum of the reported `cost_usd` of the saved results, from the last run): $0.0063.
Two earlier runs of the same script (a first run, and one repeated to fix two checks in the
script itself) cost $0.0078 and $0.0060; their outputs were overwritten. Total about $0.02, against
the $0.30 budget.

| Item | Result |
|---|---|
| (a) PNG, PDF, text file, HTTPS image URL, HTTPS PDF URL on `openai/gpt-6-luna` and on depth `fast` | 10 of 10 completed; the answers came from the attachment (`Red`, `MANGO`, `PAPAYA`, the Python logo, a sample PDF). Model route $0.00001 to $0.00009 per call; `fast` $0.00103 to $0.00162 |
| (b) chat: PDF first turn, chained text turn, chained question about the PDF, a chained turn that adds an image, a replay, the file attached again, a chained turn after the restart | all `MANGO` or `Red` as expected; the replay without the file answered `CANNOT SEE` and carried the warning "2 earlier attachment(s) were not resent"; with the file attached again `MANGO`; the chained turn after the restart still answered `MANGO` |
| (c) refusals | `xai/grok-4.3` + PDF: local `invalid_request` naming the model and `document`, up to five accepting models; the same call with `PERPLEXITY_BASE_URL` at a closed port gave the same local error, so no request was made; audio: local `invalid_request`; a path outside `PERPLEXITY_ATTACH_ROOTS`: local; a file inside the data directory: `path is denied`; `anthropic/claude-opus-5` + PDF: run `failed`, `unexpected_response` with the refusal hint |
| (d) usage | 19 events; 17 matched a saved result and every one matched to the nano-USD (0 mismatches); the other two are the failed `claude-opus-5` run (no cost reported) and the HTTP call with roots; the database sum equals the `perplexity_usage` total (6300000 nano-USD) |
| (d) no bytes stored | the PDF's body line and `%PDF-` header, the text file's body line, and the base64 prefixes of the PDF and the PNG are in neither `perplexity.db` (nor its WAL) nor the saved stderr; chat rows hold the text plus one note line (name, type, size, short digest) |
| (e) `perplexity_models` inputs | the `inputs` column is shown for all 59 live models (`e_models_inputs.txt`); NOT run: a live refresh that probes an injected new model. The live list holds 5 models the baseline lacks and 9 models with an unknown kind, so a refresh would probe about 14 models (cap $0.25 per refresh) and could not be held to this run's budget; the probe is covered offline by `tests/test_matrix_input_probe.py` |
| (f2) HTTP transport | without `PERPLEXITY_ATTACH_ROOTS` a local path is refused ("local paths are disabled over HTTP"); with it the same call returned `MANGO` ($0.00001) |
| (f) replay-trailer question | with only the stored note, the model did not claim to have seen the file (`CANNOT SEE`) |
| (g) `reasoning.effort` with an image | not part of this release (belongs to the held `routing-v2`) |

Observations for the owner: (1) no model in the live list is recorded as refusing images (the
generic 400 is `unknown` since the 2026-11-11 amendment), so the image-refusal case of (c) could
only be shown for documents; (2) `xai/grok-4.3` is the document refusal used. No product defect
was found.

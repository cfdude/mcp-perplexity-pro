# Proposal

## Why

The Agent API now reads images and documents, and live probes on 2026-10-30 (`acceptance/probe.md`)
proved it: a PNG sent as an `input_image` part and a PDF or UTF-8 text file sent as an `input_file`
part were each read correctly by the cheapest model, at $0.00001 to $0.00005 per call, and a sweep of
all 54 listed models found 47 that accept images and 44 that accept documents. Neither this
server's tools can send them: `perplexity_ask` and `perplexity_chat` take only text, and the
request builder refuses anything but a string or a list of text messages. A caller who wants "what
is in this screenshot" or "summarize this PDF" has to leave the server, which also leaves the usage
log, the project scoping and the chat history behind. The audio half of the request cannot be
built: the API rejects every audio shape (`invalid type "input_audio"`), so this change records
that and ships images and documents only.

## What Changes

- `perplexity_ask` and `perplexity_chat` `send` gain ONE new optional parameter, `attachments`
  (at most 10 items), a LIST OF STRINGS (design D1): each is a local path, an `https://` URL or a
  `data:` URI (inline data is only ever a `data:` URI: there is no separate data plus media-type form), with an optional `type::` prefix for a URL with no extension. The kind (image or
  document) is derived from the media type, never asked for. One compact parameter instead of
  three keeps the `tools/list` growth small (design D1, D14: gross growth capped at 900 bytes,
  measured in task 3.3 against the unchanged cap 59779).
- A local `path` is read by the server (not by the model), size-checked, type-checked by its
  extension and its first bytes, checked by the opened descriptor's real path against an optional
  `PERPLEXITY_ATTACH_ROOTS` allowlist and a built-in deny list (`~/.ssh`, `~/.aws`, the data
  directory, `.env*` and the like), denied outright over the unauthenticated HTTP transport unless
  the roots are set, and sent inline as base64: images as `input_image` with a data
  URI, documents as `input_file` with `file_data`. A `url` (HTTPS, public) is passed to the API
  untouched (`image_url` or `file_url`): the provider fetches it, this server never does. Inline
  data is a caller-supplied `data:<type>;base64,...` URI of at most 1 MiB.
- File bytes are never stored locally: no migration. A chat message stores its text plus a short
  note of the attachments' names, media types, sizes and SHA-256 digests (inside the existing
  `content` text, so no new column), and a chained follow-up keeps the files through the API's own
  `previous_response_id` continuation; a replay cannot resend what was never stored and says so.
- **This change owns modality data** (no router exists in this release; `models_accepting` is the pure function the gate uses for the accepting models named in its error text): the
  kinds are `image` and `document` only. The model matrix gains a per-model `inputs` record (`image`, `document`) with a source label (`probe`,
  `baseline`, `unprobed`) and per-kind timestamps, filled in the baseline from the 2026-10-30 sweep (also for entries of an upgraded file, by the merge and a read-time fallback), probed per kind by the same refresh that probes efforts, and exposed as
  `matrix.models_accepting(kinds)`, a pure read-only function.
- An explicit `model` that the matrix records as unable to take an attachment is refused locally
  with `invalid_request` (no request, no spend); an unknown or unprobed model is let through on an explicit, pin, tier or default route and the API's own refusal is mapped to a clear `invalid_request`.
- Research (`perplexity_research`) is OUT of this change although the API allows it (a background
  `medium` run with a PDF completed on 2026-10-30): the tools-list budget has no room left for a
  third parameter and research runs are stored by the provider, so it is a follow-up
  (`media-research`, design D11, an open question with a recommendation).
- The `perplexity-pro` command line gets a repeatable `--attachments VALUE` flag through the
  existing generated-flag mapping (relative paths made absolute by the command); `help_text.py` gains an attachments topic.
- Audio: refused with a clear error naming the supported kinds; nothing is sent. Video is likewise
  unsupported by the API's document contract.

- One gate on the FINAL resolved route (explicit model, pin, tier model or default): `accepts == no` is `invalid_request` locally, `unknown` is sent for explicit, pin, tier and default routes ; a preset is
  used with media only when `preset_accepts` is `yes`.
- A chat's `inherited_kinds` (from the stored attachment notes) joins the new kinds for routing and
  the gate; a replay restarts the chain. The tools list stays under its unchanged cap of 59779 bytes, which is never raised (design D14, standalone budget; the 300-byte trim of task 3.3 is waived because the measured growth fits).
- Matrix probes for inputs have their own same-round control, per-kind eligibility, a 7-day backoff
  after two unanswered rounds and a 24-hour re-probe of refusals (owner-editable); only a NAMED modality
  refusal is recorded as refused, never the generic 400 `invalid request` or a 429 (2026-11-11 investigation:
  `xai/grok-4.7` accepts image and document, the 2026-10-30 refusal was stale).
- This change also owns the single predicate `matrix.model_not_served(status, message, model)` (a 400 `validation failed: model ... is not supported`; a 404 or a 410 only when the message names the requested model), used by the baseline rules and the input probe, and the named-refusal predicate `matrix.is_named_refusal`.
- **Release scope (owner decision 2026-11-19).** `media-inputs` ships on its own, on branch `epic/media-inputs` cut from `main`. `routing-v2` is held on branch `epic/routing-v2-media-inputs` and is not part of this release: nothing here uses its router, evidence file, migration `0006`, `chat_messages.tier`/`routed_model`, task class or `PERPLEXITY_ROUTER_MARGIN`. The only seam is `resolve(required_input=...)`, owned here and ignored by every path (`acceptance/split-plan.md`, which lists the router-dependent wording this release removed).
- **Apply order** (this release): (0) worktree, Gate 1, split readiness; (1) probes and matrix input facts (1.1 to 1.3, 2.1, 2.2); (2) the call flow and the attachments parameter on ask and chat (1.4, 1.5, 2.3, 2.4, 3.1, 3.2); (3) the budget measure and the help topic (4.1, 4.2, 3.3); (4) the live acceptance (5.1); (5) the code freeze and Gate 2 (6.1 to 6.5); (6) documentation (7.1, 7.2); (7) archive (7.3).

## Resolves

- R1: a caller can send images and documents through `perplexity_ask` and `perplexity_chat` `send` (one `attachments` list of strings; paths, HTTPS URLs, `data:` URIs).
- R2: a local file read is safe: real-path checks, roots, a deny list, a uniform refusal under roots, no leak of descriptors or memory, nothing stored or logged.
- R3: a model that cannot take a kind is not sent it (a gate on the final route), an unknown one is let through, and a refusal expires.
- R4: the model matrix owns modality facts (`inputs`, `accepts`, `models_accepting`, `preset_accepts`), baselined from the 2026-10-30 sweep and probed per kind within the refresh limits.
- R5: a chat keeps its files through the API's own continuation, notes them without storing bytes, limits its documents, and a replay says what it cannot resend.
- R6: costs, errors and hints are honest: attachments add input tokens, one hint order, no echo of contents or signed URLs.
- R7: the command line, help topic and `perplexity_models` show it all, inside the unchanged `tools/list` cap of 59779 bytes.

## Capabilities

### New Capabilities
- `media-attachments`: what an attachment is, how it is validated, read and sent, its limits and
  safety rules (path handling, no logging of contents), cost recording and the model gate.

### Modified Capabilities
- `agent-ask`: `perplexity_ask` takes `attachments`; the request's input becomes a user message of
  parts; the tool's schema budget is pinned.
- `agent-chat`: `send` takes `attachments`; what is stored for a turn with attachments; follow-up
  and replay behavior.
- `model-matrix`: the per-model `inputs` record, its baseline, its probe and `models_accepting`.
- `model-catalog`: `perplexity_models` shows each model's accepted inputs.
- `cli`: the `--attachments` flag.
- `help-tool`: the attachments topic.

## Impact

- Code: new `media.py` (pure: validation, reading, building parts), `agent.build_request` (accepts
  parts), `tools/ask.py` and `tools/chat.py` (the parameter and the model gate), `matrix.py` (the
  `inputs` record, `models_accepting`, the probe), `matrix_refresh.py` (one more probe request per new
  model, within the existing budget), `command.py` (the flag mapping), `help_text.py`, `catalog` output
  of `perplexity_models`; the baseline `data/model_matrix_baseline.json` regenerated for `inputs`.
- No database migration. The matrix file version stays 1 (a missing `inputs` reads as `unprobed`,
  design D6).
- Tests: offline through `httpx2.MockTransport`; real scrubbed responses captured as fixtures
  (listed in `design.md` "Fixtures to capture").
- Cost: media tokens are billed by the model; the existing `run_costed` path records them. The
  tool descriptions state that a document or image can cost more than the text figures.
- Sibling change `routing-v2` is held (not part of this release); it would call `matrix.models_accepting`, which this change owns with its scenarios.

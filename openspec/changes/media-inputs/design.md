# Design

## Context

Everything below marked "observed" is from live calls made on 2026-10-30 with the funded key
against `POST https://api.perplexity.ai/v1/agent`, through a throwaway script (not this server),
on cheap models and with 48 by 48 pixel images and one-line documents. The raw captures and the
per-model sweep are in `acceptance/probe.md` and `acceptance/sweep.json`; total spend is stated
there. Where a probe contradicted the documentation (`docs.perplexity.ai/docs/agent-api/
image-attachments`, `working-with-files`, the OpenAPI `InputContentPart`) the probe wins and the
difference is named (`docs/lessons/docs-lie-probe-the-api-first.md`).

### Observed API shapes (2026-10-30)

| Probe | Request item | Result |
|---|---|---|
| image, inline | message content part `{"type":"input_image","image_url":"data:image/png;base64,..."}` | 200, the model named the colour; 39 input tokens for a 48 by 48 PNG |
| image, inside `{"type":"message","role":"user","content":[...]}` | same part | 200, identical (the house item shape with `type: message` is accepted) |
| image, data URI of 6544 characters | same | 200 (the OpenAPI `maxLength: 2048` on `image_url` does not apply to data URIs) |
| image bytes labelled with another type, SVG, BMP | | PNG as `image/jpeg`: 200 (the API sniffs the bytes); SVG and BMP: 400 `invalid base64 image format. Supported types: jpeg, png, gif, webp` |
| image, HTTPS URL | `image_url` an `https://` URL | 200 (the provider fetched it); an `http://` image URL was also accepted (undocumented), an `http://` `file_url` is refused with 400 `file_url must be an HTTPS URL without credentials or fragment`: this server refuses http for both |
| document, inline | `{"type":"input_file","filename":"doc.pdf","file_data":"<base64>"}` | 200, the model quoted the PDF's text |
| document, DOC, DOCX, RTF (Gate 1 follow-up) | `input_file` with `filename` `k.doc`, `k.docx`, `k.rtf` (made with `textutil`) | 200 each, the text read correctly |
| document, text file as data URI | `file_data` `data:text/plain;base64,...`, `filename` `note.txt` | 200, the model quoted the text |
| document, URL | `{"type":"input_file","file_url":"https://..."}` | 200 |
| document with `store` false | as inline, `store` false | 200 (a document does not need `store` true) |
| document with the web search tool | as inline plus `tools:[{"type":"web_search"}]`, `max_steps` 3 | 200 (the documentation says browser tools are unavailable with documents; `web_search` is not refused) |
| image with a preset | `effort` `fast`, image part, no model | 200, served by `openai/gpt-6-luna`, cost $0.00175 of which $0.001 the search call |
| audio | `{"type":"input_audio",...}` (inline data or a URL), a WAV as `input_file`, `input_video` | 400 `invalid type "input_audio"`, 400 `unsupported document type; use PDF, DOC, DOCX, TXT, or RTF`, 400 `invalid type "input_video"` |
| continuation | PDF or PNG turn (`store` true or false), then `previous_response_id` with text only, or with a message holding a NEW image; also two chained hops and a model switch | 200 each; the file is kept and new parts add to it |
| research | `effort` `medium`, `background` true, `store` true, a PDF part | 200 queued, then `completed` with the right answer: the API allows research with a document |
| presets | `fast` with a PDF; `fast`, `low`, `medium` with an image | 200 each (they run `openai/gpt-6-luna` and add about 1400 input tokens of their own prompt) |
| a refusing model | `anthropic/claude-opus-5` with a one-line PDF (twice) | 200 with run status `failed`, error `refusal` `document processing failed: refusal`, no usage |
| file extension that does not match the bytes' type | `filename` `doc.docx` on PDF bytes | 400 `filename extension does not match document media type` |
| bad base64 | `file_data` `!!!notbase64!!!` | 400 `invalid file_data base64` |
| both `file_data` and `file_url` | | 400 `input_file requires exactly one of file_data or file_url` |
| a model that cannot read images | `perplexity/deepseek-v4-pro-0813`, `perplexity/glm-5.3`, `xai/grok-4.20-reasoning` | 400, body `invalid request` (the generic body that several unrelated mistakes share) |
| a document on a route that cannot read it | `xai/grok-4.20-reasoning`, `xai/grok-4.3` | 400 `the selected model route does not support this document type or source` |
| a model the Agent API does not serve | `perplexity/nemotron-3-ultra-550b-a55b` | 400 `validation failed: model ... is no[t available]` for any input |

Documents verified live: PDF, UTF-8 TXT, DOC, DOCX, RTF. Facts from the documentation that the
probes did not exercise (kept as documented, dated
2026-10-30): documents are PDF, DOC, DOCX, UTF-8 TXT and RTF; at most 30 document parts and 50 MiB
decoded inline documents, including documents inherited by a continuation; a request body of at
most 72 MiB; a `file_url` must be HTTPS, port 443, with no credentials or fragment, and "defaults
to PDF unless `filename` supplies another supported extension"; images are PNG, JPEG, WEBP and GIF,
at most 50 MB each inline; `file_id` is not supported; zero data retention makes documents
unavailable.

Not verified and therefore not specified as fact: the response to an over-size body (the 72 MiB,
50 MiB and 30-document limits are not exercised; our own caps sit well below them), `file_id`, and zero-data-retention behaviour.

## Decisions

**D1. One parameter, `attachments: list[str]`.** The tools-list budget is the scarce resource
(`tests/test_tools_list_budget.py`, cap 59779 bytes; after `routing-v2` the headroom is 1394, 968
and 734 bytes for the default, dynamic and dynamic-with-Decisions servers, see D14). Three shapes were weighed:

| Shape | Schema cost (estimate, measured in task 3.3) | CLI cost |
|---|---|---|
| `images`, `documents` and `audio` as three parameters | about 3 x 330 bytes per tool, over budget on two tools | three flags |
| `attachments: list[{kind, path, url, data, media_type, name}]` | about 700 bytes per tool (a typed object with five described properties) | `--attachments` takes JSON: awkward on a command line |
| **`attachments: list[str]`** | about 330 bytes per tool (one array of strings and one description) | `--attachments X` repeated, exactly the generated list mapping, no CLI code |

The string form puts the whole grammar in the string: a path, an `https://` URL, a `data:` URI, with
an optional `<media type>::` prefix for the one case the extension cannot answer (a download URL
without an extension). The kind is derived (D2), so the caller never states it, and a caller cannot
state a kind that disagrees with the bytes. The cost: an LLM caller has a looser contract than a
typed object. The single description and the `perplexity_help` topic carry it, and every refusal
names the item's position and the fix. Growth for ask, chat and the `perplexity_models` inputs is
bounded by D14 (a growth cap relative to the starting commit and a mandatory trim); the cap of
59779 is never raised.

**D2. The kind comes from the media type, and the media type from evidence.** A path's type is its
extension and is then CHECKED against the first bytes (signatures), so a renamed file or a
`.txt` that is binary is refused locally instead of costing a request and an unreadable answer. An
inline `data:` string states its type and is checked the same way. A URL is typed by the prefix or
the extension of its path, because this server never fetches it (D4). Audio, video and anything
unlisted are refused with a message that says the API accepts neither (observed
`invalid type "input_audio"`). A `kind` argument was rejected: it can only disagree with the
evidence.

**D3. How the bytes reach the API: read locally, send inline base64; URLs pass through.** The
request is built entirely in `media.py` (pure but for the file read), as the `input` of
`agent.build_request`. For a path the server reads the file (D5) and sends `input_image` with a data
URI or `input_file` with `file_data` (plain base64; the API takes a data URI or plain base64, and
`filename` carries the extension the API checks). A URL is sent as `image_url` or `file_url`
untouched: the provider fetches it, so this server holds no network path to arbitrary hosts and no
SSRF surface. The request `input` becomes one message item
`{"type":"message","role":"user","content":[text, parts...]}` (observed to be accepted), the same
item type the chat replay already builds. `agent.build_request` gains an `attachments` argument
(already-built parts), so `store`, tools, `instructions`, `previous_response_id` and the
preset-or-model rule stay in one place. The two `build_request` call sites that exist (ask, chat
send in three shapes) and the research builder are the call-site sweep of task 6.1.

**D4. Limits, memory and the body.** Ours: 10 attachments, 20 MiB per file, 32 MiB decoded in
total per call, 1 MiB for `data:`, and for a chat 30 documents and 50 MiB of document bytes counted from the
stored notes since the last chain restart (D7). All sit under the documented API limits (30
documents, 50 MiB, 72 MiB body); they are our chosen caps and the API's own refusals (text
unprobed) are the backstop. Memory: one call holds the raw bytes until encoded, then the base64
text, the JSON text and the encoded request, about four times its decoded size at peak, so a
process-wide condition-variable byte limiter (asyncio has no byte semaphore; 64 MiB; the share known before any read from the descriptor size or the decoded inline length and acquired for the whole call at once; a share above the limit failing at once; a 30-second wait then `rate_limited`: the closest
member of the closed vocabulary for "retry later") bounds the process near 4 x 64 MiB however many
calls arrive together. The implementation drops raw bytes once encoded and serializes the body
once. The body size is computed arithmetically before anything is encoded (4 x ceil(n/3) per item
plus the text); with the caps above it cannot exceed about 44 MiB, so the 64 MiB check is a
backstop that tests reach by lowering the module constants, not by building 65 MiB. Inline data is
capped at 1 MiB because it travels in the caller's own context.

**D5. Path safety, and the decision on the allowlist.** The caller is a model that may be steered
by text it read ("attach ~/.ssh/id_rsa"), and `path` makes the server read local files and send them
to a third party. Layers: an absolute or `~/` path only; open with `O_NOFOLLOW` and `O_NONBLOCK`,
`fstat` the descriptor as a regular file, read to one byte past the cap; then take the
DESCRIPTOR's real path (`F_GETPATH` on macOS, `/proc/self/fd` on Linux; fail closed when neither
works) and apply the roots and deny checks to it with `Path.is_relative_to` (the roots and deny
directories are `realpath`-resolved first, so `/tmp` and a symlinked `~/.ssh` behave, and the
comparison ignores case only on a case-insensitive volume, detected), never to the caller's
string (a symlinked parent or `/Users/rob/work-secrets` against root `/Users/rob/work` cannot
pass); the extension allowlist plus the signature check keeps keys, databases and executables out
even when correctly spelled. A built-in DENY list applies in every transport and beats the roots:
`~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config`, `~/.claude`, `~/.kube`, `PERPLEXITY_DATA_DIR`, and base
names `ecosystem*.cjs` and `.env*`. The HTTP server is unauthenticated, so over HTTP local paths
are DENIED unless `PERPLEXITY_ATTACH_ROOTS` is set (the refusal says how to enable) and the server
logs one line at startup when it is unset; stdio keeps allow-by-default (the person who runs it
chooses what to attach). `PERPLEXITY_ATTACH_ROOTS` is parsed from a plain string, not a pydantic
list field: pydantic-settings reads list fields as JSON from the environment and a bad value
would then break `--help` and the schema build that read the settings. Errors name the path as
written; the only logging is the kind, type, size and a 12-hex digest (D8).

**D6. The matrix owns modality data; the router asks.** This change OWNS modality data: the
`inputs` record and the three functions `accepts`, `models_accepting` and `preset_accepts`.
`routing-v2` keeps no modality table of its own (it drops `input_modalities`) and calls these.
Kinds are `image` and `document` only: text is implicit, and audio and video are refused before
any router sees them (D2).  `model_matrix.json` has no modality field today
(checked 2026-10-30: `rg modalit src/` finds none, `data/model_matrix_baseline.json` has `efforts`
only, and `/v1/models` lists id, owner and pricing only; the docs/research note carries
modalities as prose from 2026-10-15). So: an `inputs` record shaped like `efforts` (accepted,
refused, answers, probed_at, source), version staying 1 (an absent key reads `unprobed`; `ModelEntry`
already ignores extra keys), the baseline filled from the sweep (image: 47 accepted, 6 refused, 1 unprobed; document: 44
accepted, 5 refused, 5 unprobed, `acceptance/probe.md`), new models probed by the refresh
that already probes efforts. The probe is two more requests per new model (a 48 by 48 PNG and a
one-line PDF) through `probe_request`'s `costed_call`, so the `record_usage` sites stay two. A
probe asks "does the API answer 200", never "is the answer right": a model that runs out of its 150
output tokens while reasoning (observed for `openai/gpt-5-nano` and `gpt-5-mini`) is still accepting.
Because a 429 ends a refresh round and the observed account limit is three requests per short
window, input probing is last in a model's sequence and cheap to skip.

The interface for `routing-v2` is three pure functions in `matrix.py`:
`accepts(model, kinds) -> yes|no|unknown`, `models_accepting(kinds) -> set[str]` and
`preset_accepts(preset, kinds)`. `unknown` and `unprobed` never enter `models_accepting`: a router
that substitutes a model must be able to trust the set, whereas an explicit model, a pin, a tier's
model or the default route that the matrix does not know is let through (D9). The router must never silently drop an attachment: it either routes
to a model in the set or the call fails `invalid_request`.

Probe design (Gate 1). `accepts` reads the per-kind lists only; `source` is a label. The refresh's
selector `_wants_probe` gains a second test: an `available` model with a kind unknown (and past its
`retry_after`) or refused for more than 14 days (a refusal is one generic `400 invalid request`,
shared with unrelated mistakes, so it is a likely answer, not a proof, and expires). One per-kind predicate, `attempted` (an answer, or a non-null `retry_after`, or an `attempts` count
above 0 that never resets, while `unanswered_rounds` is only the backoff counter), is used by the
merge, `accepts` and `_wants_probe`: the baseline fills or answers a kind only when the stored kind is
not attempted. Baseline answers count as known only then. Each input probe has its OWN same-round control (the effort probe's control
when it ran the same round, else a fresh text request): the baseline control of 2026-10-17 was
stale by 2026-10-30, when `perplexity/nemotron-3-ultra-550b-a55b` had gone from served to `is not
supported`, and a refusal recorded against a model that stopped being served would be false. A 200
whose run `failed` (the `anthropic/claude-opus-5` document refusal) is unanswered; two unanswered
rounds set a 7-day `retry_after`, persisted in `inputs`, so a model that always fails is not paid
for on every refresh. The bookkeeping (`ANSWER_KEYS`, `_note_round`, `failed_models`,
`pending_answers`) gets an input counterpart with its own keys so one facet's failed round never
marks the other; `probed_at`, `retry_after` and `unanswered_rounds` are PER KIND so a model whose
image answers and whose document always fails still reaches the document backoff. Cost: one
control plus at most two kind requests per model; measured in `acceptance/sweep.json` (2026-10-30)
an image request averaged $0.0005 (worst $0.0037) and a document request $0.0021 (worst $0.0207,
`anthropic/claude-fable-5-1`); ten models at the worst cases would cost about $0.24 before controls
and effort probes, so a round can reach the cap and the $0.25 check before each model is what
bounds it (the README states only these measured figures). `incomplete` counts as accepted for
inputs only; the effort probe is unchanged. Upgrade: `merge` copies the baseline's answer into an existing entry for each kind that is not attempted (`matrix.py` only fills efforts for NEW ids today, so without
this a deployed file would show an empty `models_accepting` and re-probe 54 models), and
`accepts` falls back to the baseline per unattempted kind at read time. The baseline's 400 rule: `is
not supported` means unknown, any other 400 refused (tests pin 47/6/1 and 44/5/5). The version stays 1: an older server
sharing the data directory ignores `inputs` (the entry model drops unknown keys) and loses it on its
next write; the newer server re-probes at about $0.02 per model at worst, and the README says so.
A bump to 2 would instead make older servers fall back to the baseline entirely, which loses more.

**D7. Storage: nothing but a note.** File bytes never enter `perplexity.db` (they would bloat a
SQLite file that has no pruning, and a stored base64 PDF is a retention surface the tool
descriptions would then have to disclose). A chat turn's user message stores its text plus one
trailer line in the existing `chat_messages.content` column: no migration, no new column, `read`
shows it, a later send counts documents from it. File and inline items are `name (type, N bytes,
sha256 <12 hex>)`; a URL item is `host (type, url sha256 <12 hex>)`, hashing host and path and
never storing either path or query (the host passes the name sanitizer and must match `[A-Za-z0-9._-]+`, else the URL is refused), because a path token can be a capability. Names are cut to 60
characters and `; ( ) [ ]` and control characters become `_`. A trailer longer than 1500 characters
ends with `+N more: <d> documents, <i> images, <b> bytes`, so hidden items still count toward the
limits. A user line that begins `[attachments:` is stored with a leading backslash, so the last
line of a stored message is a genuine trailer or none. A replay turn in a chat that already has
notes carries the token `restart` (`[attachments: restart; ...]`), because it begins a new provider
chain whose input holds only text and that turn's own attachments: inherited kinds and document
counts start again from it. The alternative, a `chat_attachments` table, is cleaner to query and
costs a migration with a downgrade for a feature nothing queries yet.

**D8. Cost recording and logging: the existing path.** A call with attachments goes through
`agent.run_costed` unchanged, so there is no new `record_usage` site and nothing for the
call-site sweep to find beyond the one new matrix probe caller (which reuses
`matrix_refresh.probe_request`). Input tokens of media are billed by the model and come back in the
response's `usage`, so the cost is `reported`. The tool descriptions say so (no new dollar figure
except the measured probe costs in the README; any figure in `help_text.py` must also appear in
`README.md`, task 6.1). Redaction: `_echo` for any caller value in an error; a URL echoes without
query or fragment (signed URLs carry credentials); log records carry position, kind, type, size,
digest. The built body is never logged (there is no existing body log; a test pins it).

**D9. Gate and errors reuse the closed vocabulary.** Every local refusal is `invalid_request`
(a missing file is `not_found`, the one place the vocabulary already fits); a 400 from the API stays
`invalid_request` with a hint added (like `schema_hint`): the generic `invalid request` body gets "the
model may not accept images or documents; `perplexity_models` lists accepted inputs", and
the API's own descriptive texts are kept. No new category (the spec/`errors.py`/README/tests
four-way update the contract demands is not triggered). There is ONE gate, on the FINAL resolved
route: an explicit model, a pin, a tier's model, the default model, a held model and a router's
choice all go through `accepts` with the call's required kinds. `no` fails locally (no request, no
spend, up to five accepting models named); `unknown` is sent for an explicit model, a pin, a tier's
model or the default route, because the matrix lags the API and a wrong local refusal is worse than
one 400, while a held model and a router's choice need `yes` (D13a). A preset is used with media only when
`preset_accepts(preset, kinds)` is `yes` (images at `fast`, `low`, `medium`; documents at `fast`,
`medium`); otherwise the call fails locally, and a router that could pick either picks a model
from `models_accepting`. This is a decision, not an open question.

**D9b. Scrubbing and hints.** `redaction.scrub_media` is called from `redact_text` BEFORE key removal
and before any truncation, which already covers every route (the `PerplexityError` message, `api_type`
and `api_message` in `errors.py`, `log_setup.RedactingFilter._redact`, `usage._failure_text`,
`agent.clean_text` and the `ValidationError` text in `server.py` ~201); there is no per-chokepoint
list. It replaces with `[media removed]` (a) the body of every `data:` URI, from after `data:` to the first
character outside `[A-Za-z0-9+/=;,.%_-]` (whitespace, quotes and brackets end it) and (b) a run of
200 or more characters of the standard alphabet `A-Za-z0-9+/=` ONLY (not `_` or `-`: with them the
`pplx-`/`Qq7_` key prefix of `tests/test_agent_digest.py:199` would be scrubbed before key
redaction and break its assertion) containing an upper-case letter, a lower-case letter and a
digit, with `slashes * 16 <= run_length`, by one linear scan (no regex with nested quantifiers). The
mixed-case-and-digit rule keeps `"r" * 500` and SHA-256 hex digests untouched (existing tests such
as `tests/test_agent_digest.py:199` assert exactly that), and the 200 threshold keeps file paths and
ordinary identifiers. `ErrorContractMiddleware` additionally drops the `input_value` of an
`attachments` validation error; `agent._echo` (40 characters) is never used on an attachment. Hint precedence: when the request carried
attachments or inherited kinds `attachment_hint` wins over `schema_hint` (ask.py) and over the chat
`continuation_hint`, whose advice to resend with `replay` is wrong for an attachment cause. A
document refusal can also arrive as HTTP 200 with run status `failed` and error `refusal`
(observed for `anthropic/claude-opus-5`); `run_costed` raises `unexpected_response` for that and
the hint is attached there too (category unchanged: the vocabulary is closed). The gate runs
before the Decisions classifier whenever the route is knowable (explicit model, pin, or no model able
to take the kinds; a refused HELD model is rerouted, not refused, D13a), so a refused call makes no
costed classifier request, and AGAIN after it, together with `preset_accepts`, when the second
`resolve` changed the route (for instance a pinned model for the reclassified tier).

**D13a. Held models.** `routing-v2` D12 keeps a held model only when the matrix says `yes` for the
required kinds; otherwise the router chooses afresh. A follow-up therefore reroutes, and
`invalid_request` arises only when no model can take the kinds.

**D13. Wiring order and the dependency on `routing-v2`.** In ask and chat `send`: selector and
tier errors, attachment parse (kinds, sizes), provisional resolve and option validation, the real
`resolve(required_input=kinds)`, the gate, the Decisions request, the second resolve, then the gate and `preset_accepts` again on the final
route, then the project. A bad
attachment therefore costs no classifier call, and a bad tier never opens a file. `routing-v2`
task 5.4 adds the `required_input` parameter (default empty) to `routing.resolve`; our task 2.3
owns passing the kinds into `resolve(required_input=kinds)`, the gate and `attachment_hint` (task 1.5 does
parsing and hooks only; 3.1 replaces routing-v2 5.4's empty `inherited_kinds` hook with the real
function at both chat resolve sites, `chat.py:245` and `:588`), rebased on the new `ask.py` and `chat.py` flow and the
final `build_request` signature (which `routing-v2` 5.3 changes to carry `reasoning.effort`).

**D14. Budget and apply order.** The cap 59779 never rises; if the final measure cannot fit,
work stops and the owner decides. After `routing-v2` the headroom is 1394 (default), 968 (dynamic)
and 734 bytes (dynamic with Decisions). The Gate 1 reviewer's build of the plausible additions came
to about 288 (parameter) + 164 (description sentence) + 387 (a per-model `inputs` object in the
`perplexity_models` output schema) = about 1371, which does not fit. So: (a) `perplexity_models`
gets ONE short string field per model (about 120 bytes), never an object, and the count of unknown
models goes in the text only; (b) the `attachments` description sentence in each tool is at most
100 characters; (c) gross schema growth is capped at 900 bytes; (d) the trim is combined:
`routing-v2` task 6.3 trims at least 450 bytes and this change trims at least 300 more from the
descriptions of `perplexity_chat`, `perplexity_jobs`, `perplexity_embed` and the ask text it
touches (coordinated by task wording; if routing-v2's trim has not landed, ours is at least 750);
(e) the measure and our trim are a NEW task 3.3, after the chat parameter (3.1) has landed and with both changes applied; `perplexity_models`' field (2.4) is measured there too, and until then `tests/test_tools_list_budget.py` keeps only the 59779 cap (no interim ceilings that `routing-v2`'s own growth would break); `routing-v2` 6.4 then sets the final per-server ceilings from our table, never above 59779.

| Server | Headroom after routing-v2 | With both trims (450 + 300) | Our gross growth cap | Left (estimate) |
|---|---|---|---|---|
| default | 1394 | 2144 | 900 | about 1240 |
| dynamic | 968 | 1718 | 900 | about 820 |
| dynamic with Decisions | 734 | 1484 | 900 | about 580 |

Ceilings in force at each commit: until task 3.3 only the 59779 cap is asserted (`tests/test_tools_list_budget.py` holds no per-server ceiling, so `routing-v2`'s own growth cannot break it); `routing-v2` 6.2 only RECORDS figures; after 3.3 and `routing-v2` 6.4 the final per-server ceilings, taken from our table and never above 59779, are in force. This resolves the ordering problem that a measure before the chat parameter would understate our growth: the measure is 3.3, which runs after 3.1 (`tasks.md` step (4) and task 3.3).

Estimates (734 + 750 - 900 = 584 for the tightest server); the task 3.3 measurement replaces them.
Apply order (canonical, identical in `routing-v2` and the proposal): (1) media 1.1, 1.2, 1.3, 2.1, 2.2; (2) routing-v2 groups 0-4 and 5.1-5.3; (3) routing-v2 5.4, 5.5, 6.1, 6.2, then 6.3; (4) media 1.4, 1.5, 2.3, 2.4, 3.1, 3.2, 4.1, 4.2, then 3.3; (5) routing-v2 6.4; (6) docs for both (routing-v2 9.1 makes the single CLAUDE.md tools-list figures edit).

**D10. Chat.** `inherited_kinds(chat)` is the set of kinds named by the stored attachment notes; a chained send
uses `new_kinds | inherited_kinds` as the required kinds for the router and the gate. A chained follow-up sends only the new text and new attachments plus
`previous_response_id`: the API keeps earlier files (verified for a PDF and a PNG,
`acceptance/probe.md` P7 and P9), so the server must not resend them, and its local count of documents
(D4) is what keeps a long chat under the inherited limit. A replay cannot restore bytes it never
stored: it sends the stored text including the note, adds a warning with the count, gates on its
own new kinds only (it resends no earlier file), restarts the chain (D7) and the caller may attach
the files again on the replay turn. A chained send gates on `new_kinds | inherited_kinds`. The API
keeps files through two chained hops and across a model switch (verified, `S3`, `S4`). Making replay refuse would remove the only
fallback when a continuation id has expired; a warning keeps it usable. Only complete turns are
stored, as today; an incomplete answer's attachments are not noted.

**D11. Research: the API allows it; this change defers it.** The probe `P18` (2026-10-30) ran a
background `effort: medium` request with a PDF part and it completed with the right answer, so
nothing on the API side blocks it. It stays out for three reasons that are ours, not the API's:
(a) budget: after `routing-v2` and our trim (D14) the dynamic-with-Decisions server has about 580
bytes left, and a third `attachments` parameter on `perplexity_research` costs about 330 bytes plus
a description sentence, so it needs a further trim; (b) retention: research runs are `store` true by necessity, so the
provider keeps the uploaded document, which the research description and README would have to say
and the acceptance run would have to check; (c) the research path stores the query text in the job
row and `build_research_request` takes one string, so it needs the same note-not-bytes storage
decision as chat and a separate set of scenarios (a job's `result` is read later, by another
call). Recommendation: a follow-up change `media-research` reusing `media.py` unchanged, once
(a) is solved. Not in this change.

**D12. CLI and help.** The list-of-strings schema maps to a repeatable `--attachments` flag with no
code in the mapping. The one addition is path normalisation in `command.py` (a relative argument
becomes absolute against the command's cwd, `~/` expands) because the in-process command has a
meaningful cwd and the tool deliberately has none. `help_text.py` gets one topic and one line per
tool entry; its dollar figures must appear in the README.

## Fixtures to capture (implementation tasks 1.1 and 4.1)

Real, scrubbed, each with a `.meta.json`, through `tests/test_live_capture.py` (not hand-written):
`agent_image_inline.json`, `agent_document_inline.json`, `agent_document_url.json` (these three are
one cheap model each), `agent_image_unsupported_model_400.json` (body `invalid request`),
`agent_document_unsupported_route_400.json`, `agent_document_bad_extension_400.json`,
`agent_audio_invalid_type_400.json`, `agent_chat_document_chained.json` (turn 1 document,
turn 2 follow-up by `previous_response_id`, turn 3 a second chained hop), `agent_document_doc.json`,
`agent_document_docx.json`, `agent_document_rtf.json` (one tiny file each), `agent_document_failed_refusal.json`
(the `anthropic/claude-opus-5` run with status `failed`). The 2026-10-30 captures in the scratchpad
(`.../scratchpad/probe/*.json`) are the shape references; copy none of them (the lesson: scratch
is session-scoped, recapture into the repo with the capture script). The 48 by 48 PNG and the
one-line PDF used for the probes are generated by a helper (`tests/media_support.py`), not
committed as binary files except where a magic-byte test needs one.

## Risks

- **A caller is steered into attaching a sensitive file.** Mitigation: the type allowlist and
  signature check, the real-path roots check, the built-in deny list in every transport, default
  deny of paths over HTTP, no symlink follow; residual risk named in the README (an attached
  `.txt` outside the deny list is sent to the provider, and with `store` false is only hidden from
  retrieval).
- **The matrix is wrong or stale.** A model gains or loses support, or a refusal was one generic
  400 caused by something else. Mitigation: only `no` refuses locally; `unknown` goes to the API and
  its 400 is hinted; a `refused` kind is re-probed after 14 days (so it is NOT fixed by "the next
  refresh": until the TTL passes, a wrong `no` blocks the call locally, and the caller's recourse
  is another model or waiting for the re-probe). The sweep had gaps (the account's rate limit,
  header `x-ratelimit-limit: 3`; `overloaded` 429s; a failed run); those kinds are unknown in the
  baseline, and unanswered kinds back off for 7 days after two rounds.
- **The tools-list budget.** Our growth does not fit the dynamic servers after `routing-v2`
  (D14). Mitigation: the string field, the 100-character sentence, the combined trim, the measure
  in task 3.3, and the STOP rule.
- **Local reads block or read too much, memory.** FIFOs, huge files, many large calls at once.
  Mitigation: `O_NONBLOCK`, `fstat`, bounded read in `asyncio.to_thread`, the 64 MiB process-wide
  byte semaphore and the 32 MiB per-call cap (D4).
- **A second stdio or older server on the same data directory.** It drops `inputs` on its next
  write; costs at most a re-probe (D6).
- **Cost surprise.** A 20 MiB PDF can be thousands of pages of input tokens. There is no spending
  cap in this server (a known non-goal); the description says so and the result reports tokens.
- **Provider limits differ from the documentation.** The documentation says browser tools are
  unavailable with documents and that ZDR is incompatible; one of those did not reproduce
  (`web_search` worked). Mitigation: the API's refusals pass through with hints.

## Open questions (each with a recommendation)

1. **Local paths over HTTP: decided (D5).** Denied unless `PERPLEXITY_ATTACH_ROOTS` is set, with a
   startup log line when it is unset; stdio keeps allow-by-default; the deny list applies everywhere.
2. **Strings only versus an object form.** The string grammar cannot carry a display name for a
   `data:` item or a `kind` override. Recommendation: ship strings; add `{path|url|data, name}`
   objects only if a real caller needs a name, as a union, in a later change.
3. **Presets with media: decided (D9).** A preset is used with media only when `preset_accepts`
   is `yes`; otherwise a model from `models_accepting`, else a local `invalid_request`. Presets also
   add about 1400 input tokens of their own prompt, so a preset call with media costs more than a
   model call.
4. **Research with attachments.** The API allows it (`P18`). Recommendation: a separate change
   `media-research` after a description-trimming pass frees the bytes (D11); research stays
   text-only here. If Rob wants it in this release, the cheapest path is to trim the ask and chat
   `attachments` descriptions to one clause each and add the parameter to research with the same
   string list; that is a decision, not a drift.
5. **A `chat_attachments` table instead of the note.** Recommendation: the note now (no migration),
   the table when something needs to query attachments.
6. **Audio.** Unsupported by the API. Recommendation: refuse clearly now; a transcription step is a
   separate product decision (it would need a speech-to-text API this server does not have) and is
   not planned.
7. **Does the stored trailer make a replay worse?** The model reads "[attachments: ...]" as text
   and may claim to have seen the file. Recommendation: the warning names it, and the replay
   description says so; measured in the acceptance run (task 5.1).

## Out of scope (recorded)

Research and jobs with attachments, audio and video, Decisions images (separate tool and spec),
Search API images, file generation and download (`share_file`, `/v1/agent/{id}/files`), reusable
uploads (`file_id` is not supported by the API), a local file cache, a `chat_attachments` table,
image resizing or compression, PDF page counting, and the router's use of `models_accepting`
(`routing-v2`).

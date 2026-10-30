# media-attachments Specification

## ADDED Requirements

### Requirement: Attachments are a list of strings
`perplexity_ask` and `perplexity_chat` `send` SHALL accept an optional `attachments`: a list of at most 10 non-blank strings. Each string is a local path, an HTTPS URL or inline data, as the next requirements define. A blank or non-string item, any other shape or an eleventh item SHALL fail with `invalid_request` naming `attachments` and the item's position, before any file is read and before any request.

#### Scenario: Three forms
- **WHEN** a client passes `["/Users/rob/shot.png", "https://example.com/report.pdf", "data:image/png;base64,iVBORw0KGgo="]`
- **THEN** the three are classified as a path, a URL and inline data, and none is read or sent until all three have been checked

#### Scenario: Too many
- **WHEN** a client passes eleven attachments
- **THEN** the call fails with `invalid_request` naming `attachments` and the limit of 10, and no request reaches the API

#### Scenario: An empty list
- **WHEN** a client passes `attachments` `[]`
- **THEN** the call behaves exactly as one that passed no attachments

### Requirement: The grammar of an item
An item SHALL be processed in this order: an optional `<media type>::` prefix (matching `^[a-z]+/[a-z0-9.+-]+::`) is removed and remembered; the rest is classified case-insensitively on its scheme as inline data (`data:`), a URL (`https://` or `http://`) or otherwise a local path, which SHALL be absolute or start with `~/`. A prefix on a path or on inline data SHALL fail with `invalid_request` unless it equals the type derived from the item.

#### Scenario: A relative path
- **WHEN** a client passes `["shot.png"]`
- **THEN** the call fails with `invalid_request` naming `attachments[0]` and saying a path must be absolute or start with `~/`, and no file is read

#### Scenario: The prefix form
- **WHEN** a client passes `["application/pdf::https://example.com/download?id=7"]`
- **THEN** the attachment is a document whose request part carries the URL without the prefix

#### Scenario: An upper-case scheme
- **WHEN** a client passes `HTTPS://example.com/a.png` and `DATA:image/png;base64,iVBORw0KGgo=`
- **THEN** they are classified as a URL and as inline data

#### Scenario: A prefixed relative path
- **WHEN** a client passes `image/png::shot.png`
- **THEN** the call fails with `invalid_request` for the relative path, not for the prefix

### Requirement: Supported kinds and media types
The kind of an attachment SHALL be derived from its media type and never asked for. Images are `image/png`, `image/jpeg`, `image/webp` and `image/gif`. Documents are PDF, DOC, DOCX, UTF-8 TXT and RTF (`application/pdf`, `application/msword`, the OOXML word type, `text/plain`, `application/rtf`, `text/rtf`), each verified live on 2026-10-30.

#### Scenario: Kinds
- **WHEN** a client passes a `.jpg` path and a `.docx` path
- **THEN** the first is an image and the second a document

### Requirement: The media type comes from evidence
A path's media type SHALL come from its extension (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.pdf`, `.doc`, `.docx`, `.txt`, `.rtf`, case-insensitive), inline data's from its data URI (parameters such as `;charset=utf-8` before `;base64` are accepted and dropped), and a URL's from the prefix or else the extension of the URL's path. An unlisted or underivable type SHALL fail with `invalid_request` naming `attachments[i]` and listing the supported types.

#### Scenario: A URL whose type cannot be derived
- **WHEN** a client passes `["https://example.com/download?id=7"]`
- **THEN** the call fails with `invalid_request` saying the type cannot be derived and showing the `application/pdf::https://...` prefix form

#### Scenario: Data URI parameters
- **WHEN** a client passes `data:text/plain;charset=utf-8;base64,aGk=`
- **THEN** it is a TXT document and the request part carries plain base64

### Requirement: Audio and video are refused
An attachment whose media type is audio or video SHALL fail with `invalid_request` naming `attachments[i]` and saying the API accepts neither (observed 2026-10-30: `invalid type "input_audio"`, `invalid type "input_video"`, and a WAV as a file is `unsupported document type`), and SHALL never be sent.

#### Scenario: Audio refused
- **WHEN** a client passes `["/Users/rob/call.mp3"]`
- **THEN** the call fails with `invalid_request` naming `attachments[0]`, saying audio is not supported by the API, and no request reaches the API

### Requirement: A local path is opened safely
The server SHALL expand a leading `~/` only, open the path with `O_NOFOLLOW` on its final component and without blocking, require the opened descriptor to be a regular file, take the size from the descriptor and stop reading one byte past the limit. A directory, FIFO, socket, device or symbolic link SHALL fail with `invalid_request` and a missing file with `not_found`.

#### Scenario: A symlink as the final component
- **WHEN** a client passes the path of a symbolic link to a PNG
- **THEN** the call fails with `invalid_request` saying symbolic links are not followed, and the target is never opened

#### Scenario: A FIFO
- **WHEN** a client passes the path of a named pipe whose name ends in `.txt`
- **THEN** the call fails with `invalid_request` without blocking

#### Scenario: A file that grows
- **WHEN** a file passes its size check and is larger when read
- **THEN** the read stops at the limit plus one byte and the call fails with `invalid_request` for size

### Requirement: Local read errors are invalid requests
An OS error (permission denied, name too long) or a NUL byte in a path SHALL fail with `invalid_request` naming the item, never `internal_error`, and no message SHALL contain file contents.

#### Scenario: OS errors
- **WHEN** a client passes an unreadable file, a 5000-character path and a path with a NUL byte
- **THEN** each fails with `invalid_request` naming its position and none raises `internal_error`

### Requirement: The opened file's real path is checked
After opening, the server SHALL determine the descriptor's real path (`F_GETPATH` on macOS, `/proc/self/fd` on Linux) and apply the roots and deny checks to THAT path, never to the string the caller wrote, comparing with `Path.is_relative_to`, so `/Users/rob/work-secrets` is not inside `/Users/rob/work`. When the real path cannot be determined the call SHALL fail with `invalid_request`.

#### Scenario: A sibling directory with a common prefix
- **WHEN** the roots are `/Users/rob/work` and a client passes `/Users/rob/work-secrets/a.txt`
- **THEN** the call fails with `invalid_request` saying the path is outside the allowed directories

#### Scenario: A symlinked parent
- **WHEN** a path inside a root resolves outside it through a symbolic link in a parent directory
- **THEN** the call fails with `invalid_request` and the file's contents are never read

### Requirement: An allowlist of directories
When `PERPLEXITY_ATTACH_ROOTS` (a colon-separated list of absolute directories, parsed from a plain string so that an unusual value cannot break `--help` or the schema build) is set, the real path of every local attachment SHALL lie inside one of them. A bad value SHALL fail startup with a `SettingsError` naming the variable.

#### Scenario: Outside the roots
- **WHEN** `PERPLEXITY_ATTACH_ROOTS` is `/Users/rob/work` and a client passes `/Users/rob/notes.txt`
- **THEN** the call fails with `invalid_request` saying the path is outside the allowed directories, and the file is never read

### Requirement: Roots and deny directories are resolved first
The roots and the deny directories SHALL themselves be resolved with `realpath` before comparing, and the comparison SHALL ignore case only on a case-insensitive volume (detected, not assumed from the operating system).

#### Scenario: A root that is a symlink
- **WHEN** the roots are `/tmp/work`, which resolves to `/private/tmp/work`, and a client passes a file inside it
- **THEN** the file is accepted

#### Scenario: A symlinked deny directory
- **WHEN** `~/.ssh` is a symbolic link to another directory and a client passes a file in that target
- **THEN** the call fails with `invalid_request` saying the path is denied

### Requirement: Local paths are denied by default over HTTP
Over the HTTP transport, local paths SHALL be refused with `invalid_request` unless `PERPLEXITY_ATTACH_ROOTS` is set, and the message SHALL say how to enable them; URLs and inline data are unaffected. When the HTTP server starts with the variable unset it SHALL log one line saying local paths are disabled. Over stdio any readable path is allowed when the variable is unset.

#### Scenario: HTTP with no roots
- **WHEN** the server runs over HTTP with `PERPLEXITY_ATTACH_ROOTS` unset and a client passes a PNG path
- **THEN** the call fails with `invalid_request` naming the variable, and no file is opened

#### Scenario: Stdio with no roots
- **WHEN** the server runs over stdio with the variable unset and a client passes a readable PNG path
- **THEN** the file is read and sent

### Requirement: A built-in deny list applies in every transport
Whatever the transport and the roots, the real path SHALL NOT lie inside `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config`, `~/.claude`, `~/.kube` or `PERPLEXITY_DATA_DIR`, and its base name SHALL NOT match `ecosystem*.cjs` or `.env*`. A match SHALL fail with `invalid_request` before the contents are read.

#### Scenario: A denied directory inside the roots
- **WHEN** the roots include `/Users/rob` and a client passes `/Users/rob/.ssh/notes.txt`
- **THEN** the call fails with `invalid_request` saying the path is denied

#### Scenario: A denied base name
- **WHEN** a client passes `/Users/rob/work/.env.txt` or `/Users/rob/work/ecosystem.config.cjs`
- **THEN** each fails with `invalid_request`

### Requirement: File bytes must match the declared type
The first bytes of a path's file or of decoded inline data SHALL match the media type: the PNG, JPEG, WEBP and GIF signatures, `%PDF-`, the OLE signature for DOC, the ZIP signature for DOCX, `{\rtf` for RTF, and for TXT valid UTF-8 with no NUL byte. A mismatch SHALL fail with `invalid_request` naming `attachments[i]` and the file SHALL NOT be sent.

#### Scenario: Bytes that do not match the extension
- **WHEN** a client passes `/tmp/a.png` whose first bytes are `%PDF-`
- **THEN** the call fails with `invalid_request` naming `attachments[0]` and no request reaches the API

### Requirement: A URL is validated and passed through
A URL attachment SHALL use `https` (an `http` URL is `invalid_request`: the API documents HTTPS and refuses an `http` `file_url`, observed 2026-10-30), use port 443 or none, and be at most 2048 characters. It SHALL be sent as `image_url` (an image) or `file_url` (a document) untouched.

#### Scenario: Credentials in a URL
- **WHEN** a client passes `https://user:secret@example.com/a.pdf`
- **THEN** the call fails with `invalid_request` naming `attachments[0]` and the error text does not contain `secret`

#### Scenario: HTTP refused
- **WHEN** a client passes `http://example.com/a.png`
- **THEN** the call fails with `invalid_request` saying the API needs HTTPS, and no request reaches the API

#### Scenario: Odd characters
- **WHEN** a client passes `https://example.com/a\b.png` or a URL with a newline
- **THEN** each fails with `invalid_request`

### Requirement: A URL's shape is restricted
A URL SHALL be refused when it carries credentials, a fragment, a backslash or a control character, or when its host does not match `[A-Za-z0-9._-]+` (an internationalized host must be given in punycode, and an IPv6 literal is refused), so ask and chat behave the same.

#### Scenario: A non-ASCII host
- **WHEN** a client passes `https://bücher.example/a.pdf`
- **THEN** the call fails with `invalid_request` saying to use the punycode host

#### Scenario: An IPv6 literal
- **WHEN** a client passes `https://[::1]/a.png`
- **THEN** the call fails with `invalid_request`

### Requirement: A URL is never fetched by the server
This server SHALL NOT fetch a URL attachment, resolve its host or check that it is reachable: the provider retrieves it. For a document URL whose path has no supported extension the `filename` SHALL be derived from the media type (`document.pdf`, `document.docx`).

#### Scenario: A URL is not fetched
- **WHEN** a client passes `https://example.com/a.png`
- **THEN** the only request the server makes is the one to the API, with the URL in an `input_image` part

### Requirement: Attachment values are never echoed
An error text, a log record or a hint SHALL NOT repeat an attachment's contents or its secrets. A `data:` item SHALL be shown only as its position and media type. A URL SHALL be shown without credentials, query and fragment. A local path MAY be shown, as the caller wrote it and cut to 200 characters, and never the file's contents.

#### Scenario: A signed URL is not echoed
- **WHEN** a client passes `https://example.com/a.pdf?X-Amz-Signature=abc123` and the API answers with an error
- **THEN** the error text and the logs show the URL without its query string

#### Scenario: A data item is not echoed
- **WHEN** a client passes `data:image/png;base64,` followed by 5000 characters that are not valid base64
- **THEN** the error names `attachments[0]` and `image/png` and contains none of the 5000 characters

#### Scenario: A path is shown as written
- **WHEN** a client passes `/Users/rob/missing.png`
- **THEN** the `not_found` text names `/Users/rob/missing.png` and nothing from the file

### Requirement: Error text is scrubbed of media in redact_text
`redaction.redact_text` SHALL call a `scrub_media` before key removal and before any truncation, so every route through it is covered (`PerplexityError` message, `api_type` and `api_message`, `log_setup.RedactingFilter._redact`, `usage._failure_text`, `agent.clean_text`, the `ValidationError` text).

#### Scenario: A failed run's error object
- **WHEN** a 200 body's run error quotes a `data:image/png;base64,...` URI
- **THEN** the `unexpected_response` text holds `[media removed]`

#### Scenario: An upstream HTTP 400 that echoes the request
- **WHEN** the API answers HTTP 400 with a message that quotes a 300-character mixed base64 run of the request
- **THEN** the raised error's text and its `api_message` hold `[media removed]` in its place

#### Scenario: Scrubbed before truncation
- **WHEN** a base64 run straddles the 40-character echo cut
- **THEN** none of its characters appear in the shortened text

### Requirement: What scrub_media removes
`scrub_media` SHALL replace with `[media removed]` (a) the body of every `data:` URI, which runs from after `data:` to the first character outside `[A-Za-z0-9+/=;,.%_-]` (whitespace, quotes, brackets and the like end it), and (b) bare base64 runs as the next requirement defines, found by one linear scan.

#### Scenario: A data URI body ends at a quote
- **WHEN** an error shows `"data:image/png;base64,iVBOR..."` followed by more text
- **THEN** the body is replaced and the text after the closing quote is kept

### Requirement: Which bare runs are removed
A run of 200 or more characters of the standard base64 alphabet `A-Za-z0-9+/=` only (not `_` or `-`, so a `pplx-`/`Qq7_` key prefix is left to key redaction) SHALL be replaced when it contains an upper-case letter, a lower-case letter and a digit and has `slashes * 16 <= run_length`.

#### Scenario: A bare base64 run
- **WHEN** an error quotes a 300-character base64 run with mixed case and digits
- **THEN** the run is replaced

#### Scenario: Look-alikes survive
- **WHEN** an error shows a 500-character run of `r`, a 64-character hex SHA-256 digest or a 120-character absolute path
- **THEN** none of them is replaced

### Requirement: Validation errors drop attachment values
`ErrorContractMiddleware` SHALL drop the `input_value` of an `attachments` validation error, whose remaining text passes through `redact_text`.

#### Scenario: A validation error
- **WHEN** a client passes `attachments` as a list holding one integer
- **THEN** the `invalid_request` text names `attachments` and does not quote the value

### Requirement: Inline data is small and strict
Inline data SHALL decode strictly and be at most 1 MiB decoded (it travels in the caller's own context; a larger input belongs in a path or a URL). Bad base64, or a media type that does not match the decoded bytes, SHALL fail with `invalid_request`.

#### Scenario: Oversized data
- **WHEN** a client passes a `data:image/png;base64,...` string that decodes to 2 MiB
- **THEN** the call fails with `invalid_request` for size, naming `attachments[0]` and pointing to a path or a URL

#### Scenario: Bad base64
- **WHEN** a client passes `data:image/png;base64,!!!`
- **THEN** the call fails with `invalid_request` naming `attachments[0]`

### Requirement: Per-call size limits
The server SHALL enforce, before any request: at most 20 MiB decoded per file and at most 32 MiB decoded in total for a call's paths and inline data. These are this server's own caps, chosen under the API's documented limits, which remain the backstop.

#### Scenario: One file over the limit
- **WHEN** a client passes a 21 MiB PNG path
- **THEN** the call fails with `invalid_request` naming `attachments[0]` and the 20 MiB limit, and the file is not read beyond the limit

#### Scenario: Total over the limit
- **WHEN** a client passes two 17 MiB PDF paths
- **THEN** the call fails with `invalid_request` naming `attachments` and the 32 MiB total, and no request reaches the API

### Requirement: Decoded bytes in flight are bounded process-wide
The server SHALL hold a process-wide limit of 64 MiB of decoded attachment bytes in flight, implemented as a condition-variable byte limiter (asyncio's semaphore counts units, not bytes), held from the read until the request has been sent or failed. A call that cannot get its share within 30 seconds SHALL fail with `rate_limited` and a message saying this is a local wait and no Retry-After applies.

#### Scenario: Three large calls at once
- **WHEN** three calls each carry 32 MiB of decoded attachments at the same time
- **THEN** two run, the third waits for one of them to finish, and it fails with `rate_limited` if the wait passes 30 seconds

#### Scenario: No partial share
- **WHEN** a test lowers the limit to 40 MiB and two calls of 32 MiB each arrive together
- **THEN** one acquires all 32 MiB and the other none, and neither holds a partial share

#### Scenario: Released on failure
- **WHEN** a call fails after reading its files
- **THEN** its bytes are released and a later call can use them

### Requirement: A call's share is known before it reads
A call's share SHALL be known before any read (the descriptor's size for a path, the decoded length of inline data, zero for a URL) and acquired for the WHOLE call at once, and a share above the limit SHALL fail at once with `invalid_request`.

#### Scenario: A share above the limit
- **WHEN** a test lowers the limit to 16 MiB and a call needs 32 MiB
- **THEN** it fails at once with `invalid_request`, not after 30 seconds

### Requirement: The body size is computed, not built
Before any base64 is built the server SHALL compute the request body size as 4 times the ceiling of one third of each decoded size plus the text and a fixed overhead, and a body over 64 MiB SHALL fail with `invalid_request`. With the caps above the body cannot exceed about 44 MiB, so this check is a backstop that tests exercise by lowering the module constants.

#### Scenario: A computed body over the limit
- **WHEN** a test lowers the per-call cap constants and passes attachments whose computed body is 65 MiB
- **THEN** the call fails with `invalid_request` before any base64 is produced

### Requirement: The request is one message of parts
When attachments are given the request's `input` SHALL be one item `{"type": "message", "role": "user", "content": [parts]}` whose first part is `{"type": "input_text", "text": <the query or message>}`, followed by one part per attachment in the order given. `instructions`, `tools`, `max_output_tokens`, the model or preset selector and `store` SHALL be built as for a text call. With no attachments the request SHALL be exactly as before this change.

#### Scenario: Order and mixture
- **WHEN** a client passes an image, a PDF and another image
- **THEN** the parts follow the text part in that order

#### Scenario: No attachments
- **WHEN** a client asks without attachments
- **THEN** the request body is identical to the one built before this change

### Requirement: Images are sent as input_image parts
An image attachment SHALL be the part `{"type": "input_image", "image_url": <value>}` where the value is the HTTPS URL, or `data:<media type>;base64,<base64>` built from the file's bytes.

#### Scenario: An image from a path
- **WHEN** a client asks "What is in this image?" with a PNG path and an explicit image-capable model
- **THEN** the content is an `input_text` part with the question followed by an `input_image` part whose `image_url` starts with `data:image/png;base64,`

### Requirement: Documents are sent as input_file parts
A document attachment SHALL be `{"type": "input_file", "filename": <name>, "file_data": <base64>}` for a path or inline data (plain base64), or `{"type": "input_file", "file_url": <URL>, "filename": <name>}` for a URL, with exactly one of `file_data` and `file_url`. The `filename` SHALL be the base name (at most 255 UTF-8 bytes, extension matching the type); a name that does not fit SHALL be replaced by `document` plus the extension.

#### Scenario: A document from a path
- **WHEN** a client asks with `/Users/rob/report.pdf`
- **THEN** the part has `filename` `report.pdf` and `file_data` holding the file's base64, and no `file_url`

#### Scenario: A document from a URL
- **WHEN** a client asks with `https://example.com/report.pdf`
- **THEN** the part is `{"type": "input_file", "file_url": "https://example.com/report.pdf", "filename": "report.pdf"}` and has no `file_data`

### Requirement: File contents are never stored or returned
The server SHALL NOT write an attachment's bytes, base64 or data URI to the database, a result field, an error message or a usage event, and SHALL NOT log the request body at any level.

#### Scenario: A failed call stores no contents
- **WHEN** a call with a PDF path fails upstream with an error whose text echoes part of the request
- **THEN** no error text and no usage event contains the PDF's bytes or its base64

### Requirement: Attachment logging is minimal
A log record about an attachment SHALL hold at most its position, kind, media type, decoded size and the first 12 hex characters of its SHA-256.

#### Scenario: Debug logging
- **WHEN** the log level is DEBUG and a call with attachments is made
- **THEN** the records name each attachment by position, kind, type, size and short digest only

### Requirement: A known refusing model is not sent the attachment
An explicit `model` SHALL be checked against the model matrix (`accepts(model, kinds)` of `model-matrix`). When the matrix records that the model refuses a kind the call carries, the call SHALL fail with `invalid_request` naming `model` and the kind and listing up to five models the matrix records as accepting it, and no request SHALL be made.

#### Scenario: Known refusal
- **WHEN** the matrix records `perplexity/deepseek-v4-pro-0813` as refusing images and a client asks with that model and a PNG path
- **THEN** the call fails with `invalid_request` naming `model` and `image`, listing accepting models, and no request reaches the API

#### Scenario: Text-only call
- **WHEN** a client asks with no attachments and a model that refuses images
- **THEN** the call is unaffected

### Requirement: An unknown model is let through
For an explicit model, a pin, a tier's model or the default route, a model the matrix does not know, or whose kind is neither accepted nor refused, SHALL be sent the attachment and the API's own answer applies, because the matrix lags the API and a wrong local refusal is worse than one 400. A held model and a router's choice need `yes` (see `A held model is kept only when it can take the kinds`).

#### Scenario: Unknown model
- **WHEN** a client names a model the matrix does not hold, with a PNG
- **THEN** the request is sent and the API's answer is the result

### Requirement: One gate on the final route
The gate SHALL run once on the final resolved route and again if the route changes: an explicit model, a pin, a tier's model, the default model, a held model or a router's choice all pass the same `accepts` check with the call's required kinds (`new_kinds | inherited_kinds` in a chat). `no` fails with `invalid_request`.

#### Scenario: A tier model that refuses
- **WHEN** a `custom` server's light tier names a model the matrix records as refusing images and a client asks with `tier` `light` and a PNG
- **THEN** the call fails with `invalid_request` naming the tier's model and `image`, and no request reaches the API

### Requirement: Unknown is sent for explicit, pin, tier and default routes
`unknown` SHALL be sent for an explicit model, a pin, a tier's model or the default route, the API's own answer applying; a held model and a router's choice need `yes` (D13a). An attachment is never silently dropped, and the router only ever sees `image` and `document`.

#### Scenario: An unknown tier model
- **WHEN** a tier's model is not in the matrix and a client asks with that tier and a PNG
- **THEN** the request is sent with the image

#### Scenario: A router never picks an unknown model
- **WHEN** the router chooses a model for a call carrying a PNG
- **THEN** it chooses only from `models_accepting`, so a model whose image support is unknown is not chosen

### Requirement: A held model is kept only when it can take the kinds
A held model SHALL be kept only when `accepts` is `yes` for the call's required kinds; otherwise the router chooses afresh, so a follow-up reroutes and `invalid_request` arises only when no model can take the kinds (`routing-v2` D12).

#### Scenario: A held model that cannot take the kinds is replaced
- **WHEN** a chat follow-up in dynamic mode would hold a model that the matrix does not record as accepting the kinds the follow-up carries
- **THEN** the router chooses afresh from `models_accepting` and the request names that model

#### Scenario: Nothing can take the kinds in a follow-up
- **WHEN** no model in `models_accepting` for the follow-up's kinds is eligible
- **THEN** the call fails with `invalid_request` naming the kinds, and no request reaches the API

### Requirement: The gate runs before the classifier, and again after
When no model that the router could pick can take the call's kinds (the models the pins and tiers allow all refuse them), the gate SHALL fail the call before the Decisions classifier runs, so a refused call makes no costed Decisions request. When the second resolve after the classifier changed the route, the gate SHALL run again on the final route. An explicit `model` makes the classifier unnecessary, and its gate runs at once.

#### Scenario: Nothing can take the kinds
- **WHEN** a dynamic-mode call with the Decisions classifier, no selector and tier pins that all name models recorded as refusing images carries a PNG
- **THEN** the call fails with `invalid_request` and no Decisions request is made

#### Scenario: A reclassified tier whose pin refuses
- **WHEN** the Decisions classifier raises the tier and the pinned model of that tier is recorded as refusing the call's kinds
- **THEN** the second gate fails the call with `invalid_request` naming the pinned model and the kind, and no model request is made

### Requirement: A preset is used with media only when verified
A route that names a preset SHALL be sent with attachments only when `preset_accepts(preset, kinds)` is `yes`; for `unknown` the call fails with `invalid_request` naming the preset and the kinds and suggesting an explicit model or a verified depth. A router that can choose between a preset and a model SHALL choose a model from `models_accepting` when the preset is not `yes`.

#### Scenario: A verified preset
- **WHEN** a client asks with `depth` `fast` and a PNG path
- **THEN** the request has `effort` `fast`, the message of parts, and no `model` key

#### Scenario: An unverified preset
- **WHEN** a client asks with `depth` `low` and a PDF path
- **THEN** the call fails with `invalid_request` naming `depth` `low` and `document`, and no request reaches the API

### Requirement: Upstream refusals of an attachment are hinted
A 400 from the API on a call that carried attachments or inherited kinds SHALL stay `invalid_request` with a hint appended. For the generic body `invalid request` (observed 2026-10-30 for a model that cannot read images) the hint says the model may not accept images or documents and points to `perplexity_models`. For a descriptive body the API's text is kept and the hint names the kinds sent. A 429, a 5xx and a timeout SHALL be handled as for any call.

#### Scenario: A model that cannot read images
- **WHEN** the API answers 400 `invalid request` to a call that carried a PNG and the matrix did not know the model
- **THEN** the call fails with `invalid_request`, the text keeps the API's message and adds that the model may not accept images and that `perplexity_models` lists accepted inputs

#### Scenario: A document type the route refuses
- **WHEN** the API answers 400 `the selected model route does not support this document type or source`
- **THEN** the error keeps that text and adds the kinds sent

### Requirement: The attachment hint takes precedence
When a request carried attachments or inherited kinds, `attachment_hint` SHALL be applied instead of `schema_hint` and of the chat continuation hint (which tells the caller to resend with `replay`, wrong for an attachment cause); a `json_schema` hint is added only when no attachment was involved.

#### Scenario: A chained send refused for its attachment
- **WHEN** a chained chat send carrying a PNG is answered 400 `invalid request`
- **THEN** the error carries the attachment hint and does not tell the caller to resend with `replay`

### Requirement: A refusal that arrives as a failed run is hinted
A 200 whose run has status `failed` and an error of code or type `refusal` (observed 2026-10-30 for `anthropic/claude-opus-5` with a one-line PDF: `document processing failed: refusal`) on a call that carried a document SHALL keep category `unexpected_response` and carry the attachment hint saying the model refused the document and another model may read it. It is recorded as the run's status as today.

#### Scenario: Opus refuses a document
- **WHEN** a call with a PDF to `anthropic/claude-opus-5` returns status `failed` with error code `refusal`
- **THEN** the call fails with `unexpected_response`, the text names the refusal and suggests another model, and one usage event is recorded

### Requirement: Attachment calls are recorded like any other
A call with attachments SHALL go through `agent.run_costed` and be recorded exactly as the same call without attachments: one usage event with the response's reported cost, no new `record_usage` call site and no new column. The tool descriptions SHALL say that attachments add input tokens and that a call with attachments can cost more than the text-call figures.

#### Scenario: A recorded image call
- **WHEN** a client asks with a PNG and the API reports cost 0.00001 USD and 39 input tokens
- **THEN** one usage event is stored with that cost and those tokens, source `reported`

#### Scenario: A failed local check records nothing
- **WHEN** an attachment fails local validation
- **THEN** no usage event is stored and no project is created

### Requirement: Search and attachments combine
Attachments SHALL be allowed with `search` true, with the web search tool and with search filters (the API accepted a document with the web search tool on 2026-10-30). An API refusal for the documented browser-tool restriction SHALL surface as `invalid_request` with the hint above.

#### Scenario: A document with web search
- **WHEN** a client asks about a PDF with an explicit model and the default search
- **THEN** the request carries the `input_file` part and the `web_search` tool

### Requirement: Research does not take attachments
`perplexity_research` SHALL NOT have an `attachments` parameter in this change.

#### Scenario: Research schema
- **WHEN** a client lists the tools
- **THEN** `perplexity_research` has no `attachments` parameter

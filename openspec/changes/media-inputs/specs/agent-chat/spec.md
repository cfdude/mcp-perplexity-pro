# agent-chat Specification

## MODIFIED Requirements

### Requirement: Send continues a chat
A `send` with `chat_id` SHALL send only the new message (with its attachments, if any) and the response id of the chat's last stored assistant message as `previous_response_id`, and SHALL set `store` false. `title` given with a `chat_id` SHALL fail with `invalid_request`. An unknown `chat_id`, or one in another project, SHALL fail with `not_found` before any upstream call.

#### Scenario: Second turn
- **WHEN** a client sends a follow-up to a chat whose last assistant message holds the first recorded response id
- **THEN** the request carries that id as `previous_response_id`, the new message as its input and `store` false, and the answer and the new response id are stored

#### Scenario: Third turn chains from the second
- **WHEN** a third message is sent after the second
- **THEN** its request carries the second turn's response id, not the first's

#### Scenario: Unknown chat
- **WHEN** a client sends to chat 999
- **THEN** the call fails with `not_found` and no request reaches the API

#### Scenario: Chat in another project
- **WHEN** a client sends to a chat of project `a` while naming project `b`
- **THEN** the call fails with `not_found`

#### Scenario: A follow-up with a new attachment
- **WHEN** a client sends to an existing chat with one PNG
- **THEN** the request carries `previous_response_id` and an input message of parts holding the text and the PNG

### Requirement: Replay of stored history
With `replay` true, a `send` SHALL NOT use `previous_response_id`; it SHALL set `store` false and send the chat's stored messages followed by the new message as an `input` list of items `{"type": "message", "role": "user" or "assistant", "content": <string>}`, the shape the API documents for conversation state. The new message's own attachments, if any, are parts of its item (text part first); earlier attachments are not resent. When the stored text exceeds 100000 characters the result SHALL carry a warning that a replay resends all of it.

#### Scenario: Replay request
- **WHEN** a chat holds one user and one assistant message and a client sends `replay` true with a follow-up
- **THEN** the request has no `previous_response_id`, `store` false and an input of three items of type `message`: user, assistant, user, in that order with the stored texts as string content

#### Scenario: Replay without chat
- **WHEN** a client sends `replay` true without `chat_id`
- **THEN** the call fails with `invalid_request`

#### Scenario: Large history
- **WHEN** a replay resends more than 100000 characters of stored text
- **THEN** the call still goes ahead and the result carries a warning naming the size

#### Scenario: Replay with an attachment
- **WHEN** a client replays a chat and attaches one PNG
- **THEN** the last input item holds the text part and the `input_image` part and the earlier items are plain text

## ADDED Requirements

### Requirement: Send takes attachments
`send` SHALL accept the optional `attachments` of `media-attachments` on a first turn and on every later turn, with the ask tool's rules, limits and model gate. Validation SHALL happen with the other local checks, before any database access or request, so a send with a bad attachment creates no chat and makes no request. The validation-only request build SHALL NOT receive the built parts.

#### Scenario: First turn with a document
- **WHEN** a client sends `message` "Summarize this" with `title` `Q3 report` and a PDF path
- **THEN** the request has the document part, the chat is created after the answer, and the stored user message holds the text and the attachment note

#### Scenario: Bad attachment on a follow-up
- **WHEN** a client sends to chat 3 with an attachment whose bytes do not match its extension
- **THEN** the call fails with `invalid_request`, no request is made and no message is stored

### Requirement: A turn's attachments are recorded as a note
The user message stored for a turn with attachments SHALL be the message text, a newline and one trailer line `[attachments: <item>; <item>]`. A file or inline item is `<name> (<media type>, <bytes> bytes, sha256 <12 hex>)`; a URL item is `<host> (<media type>, url sha256 <12 hex of host and path>)`, never the path or query (path tokens can be capabilities), the host having passed the URL rule of `media-attachments`. No column and no migration are added.

#### Scenario: What is stored
- **WHEN** a client sends "What is in it?" with `/Users/rob/shot.png` (2048 bytes)
- **THEN** the stored user message is the text, a newline, and `[attachments: shot.png (image/png, 2048 bytes, sha256 <12 hex>)]`

#### Scenario: A signed URL
- **WHEN** a client sends `https://example.com/files/ab12token/a.pdf?X-Amz-Signature=abc`
- **THEN** the stored note shows `example.com (application/pdf, url sha256 <12 hex>)` and neither the path nor the query

### Requirement: Names in the note are sanitized
A name in the note SHALL be at most 60 characters with every `;`, `(`, `)`, `[`, `]` and control character replaced by `_`.

#### Scenario: A hostile file name
- **WHEN** a file is named `x); [attachments: y.png` followed by a newline
- **THEN** the stored note holds a name with those characters replaced and still parses as one item

### Requirement: A long note keeps its counts
A trailer longer than 1500 characters SHALL list items until the limit and end with `+N more: <d> documents, <i> images, <b> bytes` counting every hidden item, so the per-chat limits still count them. The user's text is never shortened for the note.

#### Scenario: Hidden items still count
- **WHEN** ten attachments with long names produce a note over 1500 characters
- **THEN** the note ends with `+N more: ...` and a later send counts the hidden documents toward the 30-document limit

### Requirement: The user cannot forge a note
Only the server SHALL write a trailer. When a user's message has a line that begins with `[attachments:`, the server SHALL store that line with a leading backslash, so that the last-line trailer the parser reads is always genuine, and the parser SHALL accept only the strict item grammar above. The trailer parser and the escape SHALL split lines on `\n` only, never on other Unicode line separators.

#### Scenario: A forged trailer
- **WHEN** a client sends a message whose last line is `[attachments: a.pdf (application/pdf, 1 bytes, sha256 000000000000)]` with no attachments
- **THEN** the stored line begins with `\[attachments:` and the chat counts no documents

### Requirement: No attachment bytes in the chat tables
No file bytes, base64, data URI, URL path or query SHALL be stored in any chat table; the note is how `read` shows that a turn had attachments and how a later send counts the documents already in the chat.

#### Scenario: Nothing but the note
- **WHEN** a client sends a 2 MiB PDF path and the turn is stored
- **THEN** the stored rows of the chat together are smaller than 10 KiB and the PDF's base64 prefix appears in none of them

#### Scenario: Reading a chat
- **WHEN** a client reads a chat whose first turn had an attachment
- **THEN** that user message's text ends with the trailer line

### Requirement: A chained follow-up keeps earlier attachments through the API
A chained `send` (with `chat_id`, no `replay`) SHALL carry only the new message, the new attachments and `previous_response_id`. The API keeps the earlier files through any number of continuation hops and when the model changes (verified 2026-10-30: a PDF survived two chained turns and a switch to another model), so the server SHALL NOT resend them.

#### Scenario: Question about an earlier file
- **WHEN** a first turn sent a PDF and a follow-up asks "What was the secret word?" with no attachments
- **THEN** the follow-up request carries `previous_response_id` and the plain text input, and no `input_file` part

#### Scenario: Two hops
- **WHEN** a PDF turn is followed by a text turn and then a question about the PDF, all chained
- **THEN** the third request carries only `previous_response_id` and the question, and the answer uses the PDF

### Requirement: Inherited kinds come from the stored notes
`inherited_kinds(chat)` SHALL be the set of kinds named by the attachment notes of the chat's stored user messages from the last chain restart on (including hidden items' counts). A chained send SHALL use `new_kinds | inherited_kinds` as the required kinds for the router and the model gate. A replay SHALL use `new_kinds` only, because it resends no earlier file.

#### Scenario: A follow-up to an image turn
- **WHEN** a chat's first turn sent a PNG and the follow-up names a model the matrix records as refusing images
- **THEN** the send fails with `invalid_request` naming `model` and `image`, before any request

#### Scenario: Router input
- **WHEN** a dynamic-mode follow-up with no new attachments follows a turn that sent a PDF
- **THEN** the router is given required kinds `{document}`

#### Scenario: A replay uses new kinds only
- **WHEN** a replay with no new attachments follows a turn that sent a PDF
- **THEN** the required kinds are empty (the router and the gate see no kind), because a replay resends no earlier file

#### Scenario: No notes
- **WHEN** a chat's stored messages carry no attachment notes and a send adds none
- **THEN** the required kinds are empty and routing and the gate behave as before this change

### Requirement: A replay restarts the chain and says so
A replay turn starts a new provider chain, so earlier files are no longer inherited. When the chat already has attachment notes, the replay turn's stored message SHALL carry the trailer token `restart` (`[attachments: restart; <items>]`, exactly `[attachments: restart]` when the turn has no items), and later chained sends SHALL count documents and kinds from that turn on. The per-chat document limits SHALL NOT apply to a replay's earlier attachments.

#### Scenario: Later turns after a replay
- **WHEN** a chained send follows a replay turn that added no attachments to a chat whose first turn had a PDF
- **THEN** its inherited kinds are empty and its document count starts from zero

#### Scenario: Replay with the file attached again
- **WHEN** the client replays the same chat and attaches the PNG path again
- **THEN** the last input item holds the text part and the `input_image` part, the warning still reports the earlier attachment, and the stored note is `[attachments: restart; shot.png (...)]`

### Requirement: A replay warns about files not resent
The replay result SHALL carry a warning that N earlier attachments were not resent, that the model sees only their notes, and that the files can be attached again on this turn.

#### Scenario: Replay of a chat with an image
- **WHEN** a client replays a chat whose first turn sent a PNG and adds no attachments
- **THEN** the request input holds the stored messages (the first with its trailer line as text), the result carries a warning that 1 earlier attachment was not resent, and the send succeeds

### Requirement: A chat's documents are limited
A chained send SHALL fail with `invalid_request` before any request when its documents plus the documents counted from the stored notes since the last restart would exceed 30 documents or 50 MiB of decoded document bytes (the API's documented limits, which include documents a continuation inherits). URL documents count toward the 30 and add no bytes.

#### Scenario: Documents in a long chat
- **WHEN** a chat's stored attachment notes already count 29 documents and a chained send adds two more
- **THEN** the send fails with `invalid_request` naming the limit of 30 documents per chat, before any request

### Requirement: Stored tier and routed model are not this change's
A turn with attachments SHALL store its tier and routed model exactly as `routing-v2` stores them for any turn (`chat_messages.tier` and `chat_messages.routed_model`); this change adds no attachment-named column, no revision and no tier field of its own.

#### Scenario: No attachment column
- **WHEN** the schema is compared before and after this change's commits
- **THEN** no column name contains `attachment` and this change adds no migration revision

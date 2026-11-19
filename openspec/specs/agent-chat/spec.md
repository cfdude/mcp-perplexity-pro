# agent-chat Specification

## Purpose
Defines `perplexity_chat`, the multi-turn conversation tool: a chat is kept in the local database as the source of truth, each turn continues the previous provider response, and a replay option resends the stored history when continuation is not possible.

## Requirements

### Requirement: Chat tool
The server SHALL provide `perplexity_chat` with actions `send`, `list`, `read` and `delete`, each scoped to a `project` (default `default`). It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` true and `openWorldHint` true. Its description SHALL state the per-depth costs of a send (fast about $0.001 to $0.002, low about $0.004 to $0.02, medium about $0.016 to $0.05), the active routing mode and what a send with no selector uses (the default model, or in `dynamic` mode the tier the server picks from the prompt), say that the default model's cost differs from the per-depth figures, and say that `list`, `read` and `delete` make no upstream call.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_chat` is present with typed parameters, an output schema, the three annotations above, the three costs, the mode and what a nameless send uses in its description

#### Scenario: Unknown action
- **WHEN** a client calls the tool with action `rename`
- **THEN** the call fails with `invalid_request` naming `action`

### Requirement: Description makes no retention claim
The description of `perplexity_chat` SHALL say that chat text is stored in the local database and that sends use `store` false, which only hides a response from provider retrieval, and SHALL NOT claim that the provider keeps nothing or deletes anything.

#### Scenario: Privacy wording
- **WHEN** a client lists the tools
- **THEN** the description says the local database holds the messages and that `store` false hides retrieval only, and contains no claim of non-retention

### Requirement: Chat storage
Chats SHALL be stored in two local tables, `chats` (project, title, creation and update times) and `chat_messages` (chat, role `user` or `assistant`, content, time, and for an assistant message the response id, model, preset and sources), created by migration `0003`. `chats` SHALL never reuse the id of a deleted row (`sqlite_autoincrement`). Chats belong to a project and are removed with it; their messages are removed with the chat.

#### Scenario: Migration up and down
- **WHEN** a revision-0002 database is upgraded to 0003, downgraded to 0002 and upgraded again
- **THEN** the upgrade creates both tables and takes the backup for revision 0002, the downgrade drops them and leaves `projects`, `usage_events` and their rows intact, and the second upgrade succeeds

#### Scenario: Project deletion
- **WHEN** a project owning 2 chats with 6 messages is deleted with `confirm` true
- **THEN** the chats and their messages are gone, the 2 chats are counted in `rows_removed` and the messages are not counted

#### Scenario: Ids are not reused
- **WHEN** the newest chat is deleted and a new chat is created, then a send names the deleted chat's id
- **THEN** the new chat has a different id and the send fails with `not_found` instead of appending to the new chat

### Requirement: Actions that store nothing never create a project
`list`, `read`, `delete` and a `send` that names a `chat_id` SHALL look the project up and never create it. In an absent project `list` SHALL return no chats with total 0, and `read`, `delete` and `send` SHALL fail with `not_found`. A `chat_id` of `read`, `delete` or `send` that is not a positive integer below 2**63 SHALL fail with `invalid_request`, also in an absent project, while an unknown positive id SHALL fail with `not_found`. Only a `send` that starts a chat creates its project.

#### Scenario: List in an absent project
- **WHEN** a client lists chats of project `ghost`, which does not exist
- **THEN** the result has no chats and total 0, and project `ghost` still does not exist

#### Scenario: Read or send in an absent project
- **WHEN** a client reads chat 1, or sends to chat 1, naming the absent project `ghost`
- **THEN** each call fails with `not_found`, no request reaches the API and project `ghost` still does not exist

#### Scenario: An id the database cannot hold
- **WHEN** a client reads chat 0, chat -1, and chat 9223372036854775808 (2**63), the last naming the absent project `ghost`
- **THEN** each call fails with `invalid_request` naming `chat_id`, no request reaches the API and `ghost` still does not exist, while chat 999 of an existing project fails with `not_found`

### Requirement: Send starts a chat
A `send` without `chat_id` SHALL require `title` (1 to 120 characters after trimming) and a `message` that is not blank and has at most 20000 characters, and SHALL create the chat only after the upstream call has succeeded, storing the chat and both messages in one unit of work, so a failed first send leaves no chat. The result's top-level `chat_id` is the new chat's id and its `continuation` is `new`; a chained send reports `chained` and a replay `replay`.

#### Scenario: First turn
- **WHEN** a client sends `message` with `title` `Teal notes` and the API returns the recorded first-turn response
- **THEN** a chat titled `Teal notes` exists with a user message and an assistant message holding the response id, and the result has `chat_id` equal to the new chat's id and `continuation` `new`

#### Scenario: First turn request shape
- **WHEN** a first send at the default depth reaches the API
- **THEN** the request carries the routing mode's default route (in `standard` mode with defaults, model `perplexity/sonar` and no preset; in `dynamic` mode the tier's model or preset), carries the message as its string `input`, `store` false and no `previous_response_id`

#### Scenario: Missing, blank or long title
- **WHEN** a client sends without `chat_id` and with no `title`, a title of spaces, or a title of 121 characters
- **THEN** each call fails with `invalid_request` naming `title` and no request reaches the API

#### Scenario: Blank message
- **WHEN** a client sends a message of spaces, with or without a `chat_id`
- **THEN** the call fails with `invalid_request` naming `message` and no request reaches the API

#### Scenario: Failed first turn
- **WHEN** the upstream call of a first send fails
- **THEN** no chat exists afterwards

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

### Requirement: A chat may have no id to continue from
A response id that is not `resp_`-shaped SHALL be stored as none. A chained `send` to a chat whose last assistant message has no id SHALL fail with `invalid_request` naming `chat_id` and telling the caller to send with `replay` true; it never chains from an older turn.

#### Scenario: Last turn has no usable response id
- **WHEN** a chat's last assistant message holds no usable response id and a client sends without `replay`
- **THEN** the call fails with `invalid_request` naming `chat_id` and mentioning `replay`, no request reaches the API and nothing is stored

#### Scenario: Replay recovers
- **WHEN** the same send is repeated with `replay` true
- **THEN** it goes ahead with the stored history as input

### Requirement: Send takes the ask options
`send` SHALL accept the ask tool's `depth` (`fast`, `low` or `medium`), `tier`, `model`, `search`, search filters, `instructions` and `max_output_tokens` and apply the ask tool's rules and limits for them, except that it takes no `json_schema`. Each send may choose them anew, the model or tier included; the routing rules of `routing-config` apply to a send exactly as to an ask, and a send's result and stored message record the preset only when a preset ran (null for a model route).

#### Scenario: Depth per turn
- **WHEN** a first turn is sent at depth `fast` and the next at depth `low`
- **THEN** the second request has `effort` `low` while chaining from the first response

#### Scenario: Tier per turn
- **WHEN** a first turn is sent with `tier` `light` and the next with `tier` `complex` in `custom` mode
- **THEN** the second request names the `complex` tier's model while chaining from the first response

#### Scenario: Schema refused
- **WHEN** a client passes `json_schema` to a send
- **THEN** the call fails with `invalid_request`

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

### Requirement: Failed continuation is explained
When a chained send is rejected by the API with its generic `invalid request` 400, recognized by `api_message` equal to `invalid request` with status 400 and type `invalid_request`, the tool SHALL fail with `invalid_request` saying the provider could not continue from the previous response and that `replay` true resends the stored history, and SHALL store nothing, unless the send carried new attachments (precedence is owned by `media-attachments`). Any other API error SHALL pass through unchanged.

#### Scenario: Provider cannot continue
- **WHEN** the API answers a chained send with the recorded generic 400 for an unknown `previous_response_id`
- **THEN** the call fails with `invalid_request`, the message mentions `replay`, and the chat's stored messages are unchanged

#### Scenario: Other validation error
- **WHEN** the API answers a chained send with a 400 whose message begins `validation failed:`
- **THEN** the tool's error carries that message and does not mention `replay`

#### Scenario: Only inherited kinds
- **WHEN** a chained send with no new attachment follows a PDF turn and the generic 400 rejects it
- **THEN** the message mentions `replay` and carries no attachment hint

### Requirement: Only complete turns are stored
A send whose response is `incomplete` SHALL return its result with a warning and SHALL NOT store the turn, so a chat continues from its last complete turn; an incomplete first send creates no chat, returns top-level `chat_id` null and `continuation` `new`. A response with any other status, or an error, fails as the ask tool's statuses rule says and stores nothing.

#### Scenario: Truncated turn
- **WHEN** a send returns the recorded truncated response
- **THEN** the result has status `incomplete` and a warning, the chat's messages are unchanged, and the next send chains from the earlier response

#### Scenario: Truncated first turn
- **WHEN** a first send with a title returns the recorded truncated response
- **THEN** the result has top-level `chat_id` null, `continuation` `new` and `status` `incomplete`, and no chat exists

#### Scenario: Failed run on HTTP 200
- **WHEN** a send returns a 200 whose status is `failed`
- **THEN** the call fails with `unexpected_response`, one event exists and nothing is stored

### Requirement: Chat text is redacted and capped
Upstream-originated text (a status, reason, error text, warning) SHALL be redacted and capped as the ask tool's rule "Upstream text is redacted and capped" says, and the configured key SHALL be replaced by `[redacted]` in every stored message and title.

#### Scenario: Key in a message
- **WHEN** a client sends a message or title containing the configured key
- **THEN** the stored message or title holds `[redacted]` in its place

### Requirement: Listing chats
`list` SHALL return the project's chats newest-updated first with `id`, `title`, message count and times, honoring `limit` (default 20, 1 to 100) and reporting the total and whether the list was cut. The result's top-level `chat_id` is null.

#### Scenario: Newest first
- **WHEN** a project has two chats and the older one receives a new message
- **THEN** `list` returns the older chat first

#### Scenario: Limit
- **WHEN** a project has 3 chats and `limit` is 2
- **THEN** 2 chats are returned, the total is 3 and the list is marked truncated

### Requirement: Reading a chat
`read` SHALL require a `chat_id`, return that chat's messages from local storage in chronological order, the last `limit` of them (default 50, 1 to 200), with the total count, and make no upstream call. The result's top-level `chat_id` is that chat's id.

#### Scenario: Read from local history
- **WHEN** a client reads a chat with 4 messages
- **THEN** the 4 messages are returned in order with their roles and texts, no request reaches the API and no usage event is created

#### Scenario: Missing id or bad limit
- **WHEN** a client reads or deletes without `chat_id`, or lists or reads with `limit` 0, 101 (list) or 201 (read)
- **THEN** each call fails with `invalid_request` naming `chat_id` or `limit` and no request reaches the API

### Requirement: Deleting a chat
`delete` SHALL require a `chat_id` and `confirm` true (else `confirmation_required`), remove the chat and its messages, and return how many as `messages_removed`. It SHALL make no upstream call; copies the provider keeps are not touched.

#### Scenario: Confirmed delete
- **WHEN** a client deletes a chat with 4 messages with `confirm` true
- **THEN** the chat and its messages are gone and the result has `messages_removed` 4

#### Scenario: Not confirmed
- **WHEN** a client deletes without `confirm`
- **THEN** the call fails with `confirmation_required` and the chat remains

### Requirement: Send is recorded
Each send that reaches the API SHALL be recorded once as tool `perplexity_chat`, API family `agent`, with the requested preset, the resolved model, the response id and the project name, by the same status rules as the ask tool (completed is `ok`, incomplete is `unexpected_response`, a failure carries its category). The project SHALL be resolved and committed before the call and the event recorded before the chat's own write.

#### Scenario: One event per send
- **WHEN** a first send and a follow-up each complete
- **THEN** two events exist, both `ok`, with distinct response ids, and `list`, `read` and `delete` added none

#### Scenario: Failed continuation is recorded
- **WHEN** the recorded generic 400 rejects a chained send
- **THEN** one event exists with status `invalid_request` and cost 0

### Requirement: A failed local write does not discard a billed answer
When the chat's own write fails after a completed upstream call, the send SHALL return its result with a warning `not_saved` and the usage event SHALL remain; the turn is not stored. When the write fails because the chat or its project no longer exists (deleted during the call), the send SHALL fail with `not_found`, not `storage_busy`.

#### Scenario: Own write fails
- **WHEN** the chat's own write fails with a busy database after a completed upstream call
- **THEN** the result carries the answer and a `not_saved` warning, the usage event remains and no messages are stored

#### Scenario: Chat deleted during the send
- **WHEN** the chat is deleted by another call while a send to it is in flight
- **THEN** the send fails with `not_found`, one event exists and no message was stored

### Requirement: Send takes attachments
`send` SHALL accept the optional `attachments` of `media-attachments` on a first turn and on every later turn, with the ask tool's rules, limits and model gate; the order of the steps is the chat order of `agent-ask`. Validation SHALL happen with the other local checks, before any database access or request, so a send with a bad attachment creates no chat and makes no request. The validation-only request build SHALL NOT receive the built parts.

#### Scenario: First turn with a document
- **WHEN** a client sends `message` "Summarize this" with `title` `Q3 report` and a PDF path
- **THEN** the request has the document part, the chat is created after the answer, and the stored user message holds the text and the attachment note

#### Scenario: Bad attachment on a follow-up
- **WHEN** a client sends to chat 3 with an attachment whose bytes do not match its extension
- **THEN** the call fails with `invalid_request`, no request is made and no message is stored

### Requirement: A turn's attachments are recorded as a note
The user message stored for a turn with attachments SHALL be the message text, a newline and one trailer line in the grammar of the first scenario, which is defined there and nowhere else. No column and no migration SHALL be added.

#### Scenario: The trailer grammar
- **WHEN** a turn with attachments is stored
- **THEN** its last line matches `trailer := "[attachments: " [ "restart; " ] item { "; " item } "]"` (or exactly `[attachments: restart]` for a replay turn with no items), where `item := file | url | more`; `file := <name> (<media type>, <bytes> bytes, sha256 <12 hex>)` for a file or inline item; `url := <host> (<media type>, url sha256 <12 hex of host and path>)`, never the path or query because path tokens can be capabilities, the host having passed the URL rule of `media-attachments`; `more := +N more: <d> documents, <i> images, <b> bytes`, the tail of a trailer cut at 1500 characters, where `b` is the sum of the decoded sizes of ALL N hidden items, images included; `restart` marks a replay turn

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
A trailer longer than 1500 characters SHALL list items until the limit and end with the `more` item of the grammar above counting every hidden item, so the per-chat limits still count them (the parser adds the tail's bytes to the document bytes, which is conservative when images are hidden). The user's text is never shortened for the note.

#### Scenario: Hidden items still count
- **WHEN** ten DOCX attachments (each with a 60-character name, whose note is about 160 characters because of the long OOXML media type) produce a note over 1500 characters
- **THEN** the note ends with `+N more: <d> documents, <i> images, <b> bytes` and a later send counts the hidden documents toward the 30-document limit

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
`inherited_kinds(chat)` SHALL be the set of kinds named by the attachment notes of the chat's stored user messages from the last chain restart on (including hidden items' counts). A chained send SHALL use `new_kinds | inherited_kinds` as the required kinds for the model gate. A replay SHALL use `new_kinds` only, because it resends no earlier file.

#### Scenario: A follow-up to an image turn
- **WHEN** a chat's first turn sent a PNG and the follow-up names a model the matrix records as refusing images
- **THEN** the send fails with `invalid_request` naming `model` and `image`, before any request

#### Scenario: Inherited kinds reach the gate
- **WHEN** a dynamic-mode follow-up with no new attachments follows a turn that sent a PDF
- **THEN** the gate is given required kinds `{document}`

#### Scenario: A replay uses new kinds only
- **WHEN** a replay with no new attachments follows a turn that sent a PDF
- **THEN** the required kinds are empty (the gate sees no kind), because a replay resends no earlier file

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

### Requirement: No stored column of this change's own
This change SHALL add no attachment-named column, no migration revision and no tier or routed-model field to `chat_messages`; a turn with attachments stores its text plus the note line and nothing else.

#### Scenario: No attachment column
- **WHEN** the schema is compared before and after this change's commits
- **THEN** no column name contains `attachment` and this change adds no migration revision

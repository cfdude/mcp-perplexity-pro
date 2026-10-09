# Spec Delta

## Purpose

Defines `perplexity_chat`, the multi-turn conversation tool: a chat is kept in the local database as the source of truth, each turn continues the previous provider response, and a replay option resends the stored history when continuation is not possible.

## ADDED Requirements

### Requirement: Chat tool
The server SHALL provide `perplexity_chat` with actions `send`, `list`, `read` and `delete`, each scoped to a `project` (default `default`). It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` true and `openWorldHint` true. Its description SHALL state the per-depth costs of a send (fast about $0.001 to $0.002, low about $0.004 to $0.02, medium about $0.016 to $0.05) and that `list`, `read` and `delete` make no upstream call.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_chat` is present with typed parameters, an output schema, the three annotations above and the three costs in its description

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
- **THEN** the request has preset `fast`, the message as its string `input`, `store` false and no `previous_response_id`

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
A `send` with `chat_id` SHALL send only the new message and the response id of the chat's last stored assistant message as `previous_response_id`, and SHALL set `store` false. `title` given with a `chat_id` SHALL fail with `invalid_request`. An unknown `chat_id`, or one in another project, SHALL fail with `not_found` before any upstream call.

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

### Requirement: A chat may have no id to continue from
A response id that is not `resp_`-shaped SHALL be stored as none. A chained `send` to a chat whose last assistant message has no id SHALL fail with `invalid_request` naming `chat_id` and telling the caller to send with `replay` true; it never chains from an older turn.

#### Scenario: Last turn has no usable response id
- **WHEN** a chat's last assistant message holds no usable response id and a client sends without `replay`
- **THEN** the call fails with `invalid_request` naming `chat_id` and mentioning `replay`, no request reaches the API and nothing is stored

#### Scenario: Replay recovers
- **WHEN** the same send is repeated with `replay` true
- **THEN** it goes ahead with the stored history as input

### Requirement: Send takes the ask options
`send` SHALL accept the ask tool's `depth` (`fast`, `low` or `medium`), `model`, `search`, search filters, `instructions` and `max_output_tokens` and apply the ask tool's rules and limits for them, except that it takes no `json_schema`. Each send may choose them anew.

#### Scenario: Depth per turn
- **WHEN** a first turn is sent at depth `fast` and the next at depth `low`
- **THEN** the second request names preset `low` while chaining from the first response

#### Scenario: Schema refused
- **WHEN** a client passes `json_schema` to a send
- **THEN** the call fails with `invalid_request`

### Requirement: Replay of stored history
With `replay` true, a `send` SHALL NOT use `previous_response_id`; it SHALL set `store` false and send the chat's stored messages followed by the new message as an `input` list of items `{"type": "message", "role": "user" or "assistant", "content": <string>}`, the shape the API documents for conversation state. When the stored text exceeds 100000 characters the result SHALL carry a warning that a replay resends all of it.

#### Scenario: Replay request
- **WHEN** a chat holds one user and one assistant message and a client sends `replay` true with a follow-up
- **THEN** the request has no `previous_response_id`, `store` false and an input of three items of type `message`: user, assistant, user, in that order with the stored texts as string content

#### Scenario: Replay without chat
- **WHEN** a client sends `replay` true without `chat_id`
- **THEN** the call fails with `invalid_request`

#### Scenario: Large history
- **WHEN** a replay resends more than 100000 characters of stored text
- **THEN** the call still goes ahead and the result carries a warning naming the size

### Requirement: Failed continuation is explained
When a chained send is rejected by the API with its generic `invalid request` 400, recognized by `api_message` equal to `invalid request` with status 400 and type `invalid_request`, the tool SHALL fail with `invalid_request` saying the provider could not continue from the previous response and that `replay` true resends the stored history, and SHALL store nothing. Any other API error SHALL pass through unchanged.

#### Scenario: Provider cannot continue
- **WHEN** the API answers a chained send with the recorded generic 400 for an unknown `previous_response_id`
- **THEN** the call fails with `invalid_request`, the message mentions `replay`, and the chat's stored messages are unchanged

#### Scenario: Other validation error
- **WHEN** the API answers a chained send with a 400 whose message begins `validation failed:`
- **THEN** the tool's error carries that message and does not mention `replay`

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

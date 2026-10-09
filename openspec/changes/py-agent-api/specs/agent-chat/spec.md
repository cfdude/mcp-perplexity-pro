# Spec Delta

## Purpose

Defines `perplexity_chat`, the multi-turn conversation tool: a chat is kept in the local database as the source of truth, each turn continues the previous provider response, and a replay option resends the stored history when continuation is not possible.

## ADDED Requirements

### Requirement: Chat tool
The server SHALL provide `perplexity_chat` with actions `send`, `list`, `read` and `delete`, each scoped to a `project` (default `default`). It SHALL advertise an output schema, `destructiveHint` true and `openWorldHint` true. Its description SHALL state the per-depth costs of a send (fast about $0.001 to $0.002, low about $0.004 to $0.02, medium about $0.016 to $0.05) and that `list`, `read` and `delete` make no upstream call.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_chat` is present with typed parameters, an output schema and the three costs in its description

#### Scenario: Unknown action
- **WHEN** a client calls the tool with action `rename`
- **THEN** the call fails with `invalid_request` naming `action`

### Requirement: Chat storage
Chats SHALL be stored in two local tables, `chats` (project, title, creation and update times) and `chat_messages` (chat, role `user` or `assistant`, content, time, and for an assistant message the response id, model, preset and sources), created by migration `0003`. Chats belong to a project and are removed with it; their messages are removed with the chat.

#### Scenario: Migration up and down
- **WHEN** a revision-0002 database is upgraded to 0003, downgraded to 0002 and upgraded again
- **THEN** the upgrade creates both tables and takes the backup for revision 0002, the downgrade drops them and leaves `projects`, `usage_events` and their rows intact, and the second upgrade succeeds

#### Scenario: Project deletion
- **WHEN** a project owning 2 chats with 6 messages is deleted with `confirm` true
- **THEN** the chats and their messages are gone, the 2 chats are counted in `rows_removed` and the messages are not counted

### Requirement: Send starts a chat
A `send` without `chat_id` SHALL require `title` (1 to 120 characters after trimming) and a non-blank `message`, and SHALL create the chat only after the upstream call has succeeded, storing the chat and both messages in one unit of work, so a failed first send leaves no chat. The result carries the new `chat_id`.

#### Scenario: First turn
- **WHEN** a client sends `message` with `title` `Teal notes` and the API returns the recorded first-turn response
- **THEN** a chat titled `Teal notes` exists with a user message and an assistant message holding the response id, and the result names `continuation` `new`

#### Scenario: Missing title
- **WHEN** a client sends without `chat_id` and without `title`
- **THEN** the call fails with `invalid_request` naming `title` and no request reaches the API

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

### Requirement: Send takes the ask options
`send` SHALL accept the ask tool's `depth` (`fast`, `low` or `medium`), `model`, `search`, search filters, `instructions` and `max_output_tokens` and apply the ask tool's rules for them, except that it takes no `json_schema`. Each send may choose them anew.

#### Scenario: Depth per turn
- **WHEN** a first turn is sent at depth `fast` and the next at depth `low`
- **THEN** the second request names preset `low` while chaining from the first response

#### Scenario: Schema refused
- **WHEN** a client passes `json_schema` to a send
- **THEN** the call fails with `invalid_request`

### Requirement: Replay of stored history
With `replay` true, a `send` SHALL NOT use `previous_response_id`; it SHALL send the chat's stored messages followed by the new message as an input list of `message` items with roles `user` and `assistant`, so a chat can continue when the provider cannot continue from its stored response.

#### Scenario: Replay request
- **WHEN** a chat holds one user and one assistant message and a client sends `replay` true with a follow-up
- **THEN** the request has no `previous_response_id` and an input of three message items: user, assistant, user, in that order with the stored texts

#### Scenario: Replay without chat
- **WHEN** a client sends `replay` true without `chat_id`
- **THEN** the call fails with `invalid_request`

### Requirement: Failed continuation is explained
When a chained send is rejected by the API with its generic `invalid request` 400, the tool SHALL fail with `invalid_request` saying the provider could not continue from the previous response and that `replay` true resends the stored history, and SHALL store nothing. Any other API error SHALL pass through unchanged.

#### Scenario: Provider cannot continue
- **WHEN** the API answers a chained send with the recorded generic 400 for an unknown `previous_response_id`
- **THEN** the call fails with `invalid_request`, the message mentions `replay`, and the chat's stored messages are unchanged

#### Scenario: Other validation error
- **WHEN** the API answers a chained send with a 400 whose message begins `validation failed:`
- **THEN** the tool's error carries that message and does not mention `replay`

### Requirement: Only complete turns are stored
A send whose response is not `completed` (an `incomplete` run) SHALL return its result with a warning and SHALL NOT store the turn, so the chat still continues from its last complete turn.

#### Scenario: Truncated turn
- **WHEN** a send returns the recorded truncated response
- **THEN** the result has status `incomplete` and a warning, the chat's messages are unchanged, and the next send chains from the earlier response

### Requirement: Listing chats
`list` SHALL return the project's chats newest-updated first with `id`, `title`, message count and times, honoring `limit` (default 20, 1 to 100) and reporting the total and whether the list was cut.

#### Scenario: Newest first
- **WHEN** a project has two chats and the older one receives a new message
- **THEN** `list` returns the older chat first

#### Scenario: Limit
- **WHEN** a project has 3 chats and `limit` is 2
- **THEN** 2 chats are returned, the total is 3 and the list is marked truncated

### Requirement: Reading a chat
`read` SHALL return a chat's messages from local storage in chronological order, the last `limit` of them (default 50, 1 to 200), with the total count, and SHALL make no upstream call.

#### Scenario: Read from local history
- **WHEN** a client reads a chat with 4 messages
- **THEN** the 4 messages are returned in order with their roles and texts, no request reaches the API and no usage event is created

### Requirement: Deleting a chat
`delete` SHALL require `confirm` true (else `confirmation_required`), remove the chat and its messages, and return how many messages were removed. It SHALL make no upstream call; copies the provider keeps are not touched.

#### Scenario: Confirmed delete
- **WHEN** a client deletes a chat with 4 messages with `confirm` true
- **THEN** the chat and its messages are gone and the result reports 4 messages removed

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

#### Scenario: Own write rolls back
- **WHEN** the chat's own write fails after a completed upstream call
- **THEN** the usage event remains and the chat's messages are not stored

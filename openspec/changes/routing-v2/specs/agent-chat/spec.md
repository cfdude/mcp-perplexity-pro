# Spec Delta

## MODIFIED Requirements

### Requirement: Chat tool
The server SHALL provide `perplexity_chat` with actions `send`, `list`, `read` and `delete`, each scoped to a `project` (default `default`). It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` true and `openWorldHint` true. Its description SHALL state the per-depth costs of a send (fast about $0.001 to $0.002, low about $0.004 to $0.02, medium about $0.016 to $0.05), the active routing mode and what a send with no selector uses (the default model, or in `dynamic` mode the model and effort the server picks from the prompt), say that the default model's cost differs from the per-depth figures, and say that `list`, `read` and `delete` make no upstream call.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_chat` is present with typed parameters, an output schema, the three annotations above, the three costs, the mode and what a nameless send uses in its description

#### Scenario: Unknown action
- **WHEN** a client calls the tool with action `rename`
- **THEN** the call fails with `invalid_request` naming `action`

### Requirement: Chat storage
Chats SHALL be stored in two local tables, `chats` (project, title, creation and update times) and `chat_messages` (chat, role `user` or `assistant`, content, time, and for an assistant message the response id, model, preset, sources and, from migration `0006`, the tier and the routed model), created by migration `0003`. `chats` SHALL never reuse the id of a deleted row (`sqlite_autoincrement`). Chats belong to a project and are removed with it; their messages are removed with the chat.

#### Scenario: Migration up and down
- **WHEN** a revision-0002 database is upgraded to 0003, downgraded to 0002 and upgraded again
- **THEN** the upgrade creates both tables and takes the backup for revision 0002, the downgrade drops them and leaves `projects`, `usage_events` and their rows intact, and the second upgrade succeeds

#### Scenario: Project deletion
- **WHEN** a project owning 2 chats with 6 messages is deleted with `confirm` true
- **THEN** the chats and their messages are gone, the 2 chats are counted in `rows_removed` and the messages are not counted

#### Scenario: Ids are not reused
- **WHEN** the newest chat is deleted and a new chat is created, then a send names the deleted chat's id
- **THEN** the new chat has a different id and the send fails with `not_found` instead of appending to the new chat

### Requirement: Send starts a chat
A `send` without `chat_id` SHALL require `title` (1 to 120 characters after trimming) and a `message` that is not blank and has at most 20000 characters, and SHALL create the chat only after the upstream call has succeeded, storing the chat and both messages in one unit of work, so a failed first send leaves no chat. The result's top-level `chat_id` is the new chat's id and its `continuation` is `new`; a chained send reports `chained` and a replay `replay`.

#### Scenario: First turn
- **WHEN** a client sends `message` with `title` `Teal notes` and the API returns the recorded first-turn response
- **THEN** a chat titled `Teal notes` exists with a user message and an assistant message holding the response id, and the result has `chat_id` equal to the new chat's id and `continuation` `new`

#### Scenario: First turn request shape
- **WHEN** a first send at the default depth reaches the API
- **THEN** the request carries the routing mode's default route (in `standard` mode with defaults, model `perplexity/sonar` and no preset; in `dynamic` mode the router's model with its reasoning effort), carries the message as its string `input`, `store` false and no `previous_response_id`

#### Scenario: First turn with no attachments
- **WHEN** a first send names no attachment
- **THEN** its request, routing and stored message are those of a text-only send, with `routed_model` and `tier` set as the mode says

#### Scenario: Missing, blank or long title
- **WHEN** a client sends without `chat_id` and with no `title`, a title of spaces, or a title of 121 characters
- **THEN** each call fails with `invalid_request` naming `title` and no request reaches the API

#### Scenario: Blank message
- **WHEN** a client sends a message of spaces, with or without a `chat_id`
- **THEN** the call fails with `invalid_request` naming `message` and no request reaches the API

#### Scenario: Failed first turn
- **WHEN** the upstream call of a first send fails
- **THEN** no chat exists afterwards

## ADDED Requirements

### Requirement: An assistant message stores the routed model beside its tier
In `dynamic` mode an assistant message SHALL also store `routed_model`, the model id the call REQUESTED for a router model route (a pin included), in a nullable column added by migration `0006`; it SHALL be null for a preset, the fallback preset rung, an explicit `model` and any `standard` or `custom` mode turn. The existing `model` column keeps the API-reported id and the follow-up hold SHALL NOT read it.

#### Scenario: Requested and reported ids
- **WHEN** a routed turn requests `openai/gpt-6-luna` and the API reports `openai/gpt-5.6-luna`
- **THEN** `model` holds the reported id and `routed_model` holds `openai/gpt-6-luna`

#### Scenario: Not a router model route
- **WHEN** a turn runs preset `fast`, the fallback preset rung or an explicit `model`
- **THEN** its `routed_model` is null

### Requirement: An assistant message stores the tier that routed it
In `dynamic` mode each stored assistant message SHALL record the tier its call ran at, a named `tier` included, and null for a `depth` or `model` call or another mode, in a nullable column added by migration `0006` that a downgrade removes. A row written before the migration reads as no stored tier.

#### Scenario: A routed turn stores its tier
- **WHEN** a send in `dynamic` mode names nothing and runs at tier `complex`
- **THEN** the stored assistant message has tier `complex`

#### Scenario: A named tier is stored
- **WHEN** a send in `dynamic` mode names `tier` `light`
- **THEN** the stored assistant message has tier `light`, so the next nameless follow-up holds at least `light`

#### Scenario: A depth or model stores none
- **WHEN** a send names `depth` `fast` or an explicit `model`
- **THEN** the stored assistant message has no tier

#### Scenario: Migration is reversible without losing vectors
- **WHEN** a database holding chats and `embedding_chunks` rows tied to chat messages is upgraded to `0006` and downgraded
- **THEN** the chat rows and every `embedding_chunks` row remain, the new columns (`tier`, `routed_model`) are gone, and `backup-0005.db` was made before the upgrade

#### Scenario: Old rows
- **WHEN** a chat written before the migration is continued in `dynamic` mode
- **THEN** its previous tier is recovered from the stored preset as `routing-config` says

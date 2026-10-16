# Spec Delta

## MODIFIED Requirements

### Requirement: Chat tool
The server SHALL provide `perplexity_chat` with actions `send`, `list`, `read` and `delete`, each scoped to a `project` (default `default`). It SHALL advertise an output schema, `readOnlyHint` false, `destructiveHint` true and `openWorldHint` true. Its description SHALL state the per-depth costs of a send (fast about $0.001 to $0.002, low about $0.004 to $0.02, medium about $0.016 to $0.05), the active routing mode and what a send with no selector uses (the default model, or in `dynamic` mode the tier the server picks from the prompt), say that the default model's cost differs from the per-depth figures, and say that `list`, `read` and `delete` make no upstream call.

#### Scenario: Tool listing
- **WHEN** a client lists the tools
- **THEN** `perplexity_chat` is present with typed parameters, an output schema, the three annotations above, the three costs, the mode and what a nameless send uses in its description

#### Scenario: Unknown action
- **WHEN** a client calls the tool with action `rename`
- **THEN** the call fails with `invalid_request` naming `action`

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

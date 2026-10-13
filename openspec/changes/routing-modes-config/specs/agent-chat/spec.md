## MODIFIED Requirements

### Requirement: Send starts a chat
A `send` without `chat_id` SHALL require `title` (1 to 120 characters after trimming) and a `message` that is not blank and has at most 20000 characters, and SHALL create the chat only after the upstream call has succeeded, storing the chat and both messages in one unit of work, so a failed first send leaves no chat. The result's top-level `chat_id` is the new chat's id and its `continuation` is `new`; a chained send reports `chained` and a replay `replay`.

#### Scenario: First turn
- **WHEN** a client sends `message` with `title` `Teal notes` and the API returns the recorded first-turn response
- **THEN** a chat titled `Teal notes` exists with a user message and an assistant message holding the response id, and the result has `chat_id` equal to the new chat's id and `continuation` `new`

#### Scenario: First turn request shape
- **WHEN** a first send at the default depth reaches the API
- **THEN** the request names the routing mode's default model and no preset (in `standard` mode with defaults, `perplexity/sonar`), carries the message as its string `input`, `store` false and no `previous_response_id`

#### Scenario: Missing, blank or long title
- **WHEN** a client sends without `chat_id` and with no `title`, a title of spaces, or a title of 121 characters
- **THEN** each call fails with `invalid_request` naming `title` and no request reaches the API

#### Scenario: Blank message
- **WHEN** a client sends a message of spaces, with or without a `chat_id`
- **THEN** the call fails with `invalid_request` naming `message` and no request reaches the API

#### Scenario: Failed first turn
- **WHEN** the upstream call of a first send fails
- **THEN** no chat exists afterwards

### Requirement: Send takes the ask options
`send` SHALL accept the ask tool's `depth` (`fast`, `low` or `medium`), `tier`, `model`, `search`, search filters, `instructions` and `max_output_tokens` and apply the ask tool's rules and limits for them, except that it takes no `json_schema`. Each send may choose them anew, the model or tier included; the routing rules of `routing-config` apply to a send exactly as to an ask, and a send's result and stored message record the preset only when a preset ran (null for a model route).

#### Scenario: Depth per turn
- **WHEN** a first turn is sent at depth `fast` and the next at depth `low`
- **THEN** the second request names preset `low` while chaining from the first response

#### Scenario: Tier per turn
- **WHEN** a first turn is sent with `tier` `light` and the next with `tier` `complex` in `custom` mode
- **THEN** the second request names the `complex` tier's model while chaining from the first response

#### Scenario: Schema refused
- **WHEN** a client passes `json_schema` to a send
- **THEN** the call fails with `invalid_request`

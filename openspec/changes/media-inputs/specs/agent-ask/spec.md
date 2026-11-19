# agent-ask Specification

## ADDED Requirements

### Requirement: Ask takes attachments
`perplexity_ask` SHALL accept the optional `attachments` of `media-attachments`. The query stays required and an attachment never replaces it. A call with no `attachments`, or an empty list, SHALL build the request it built before this change. The parameter is a list of strings with one description, and its sentence in the tool description is at most 100 characters (the wording caps are owned by `help-tool`).

#### Scenario: Question about an image
- **WHEN** a client asks "What colour is this?" with `model` `openai/gpt-6-luna` and a PNG path
- **THEN** the request is a single user message whose content is the text part and one `input_image` part, the answer and sources are digested as for any ask, and one usage event is stored

#### Scenario: Attachments with a preset
- **WHEN** a client asks with `depth` `fast` and a PNG path
- **THEN** the request has `effort` `fast` and the message-of-parts input, and carries no `model` key

### Requirement: Attachments are checked before anything is stored
All attachment validation, reading and model checks SHALL happen before the project is resolved, so a call whose attachments fail validation stores nothing and spends nothing.

#### Scenario: Validation before the project
- **WHEN** a client asks with project `new-project` and an attachment path that does not exist
- **THEN** the call fails with `invalid_request` or `not_found` naming `attachments[0]`, and project `new-project` still does not exist

#### Scenario: Structured output with an attachment
- **WHEN** a client asks with `json_schema` and a PDF
- **THEN** the request carries both the `response_format` and the `input_file` part

### Requirement: Attachments are wired in a fixed order
The order of a call that may carry attachments SHALL be fixed, and this requirement is its ONE owner (`media-attachments` and `agent-chat` refer to it). Each failure SHALL stop the call, and nothing before the project step SHALL store or spend anything.

#### Scenario: The order in ask
- **WHEN** `perplexity_ask` runs
- **THEN** the steps are: (1) selector and tier errors; (2) attachment parsing, pure, nothing read; (3) a provisional resolve and the validation of every option; (4) the real `resolve` with the required kinds; (5) the gate, tentative when the Decisions classifier will still choose the tier (refused only when every tier's route is refused); (6) the files are read, the call's WHOLE share of the process-wide byte limiter is acquired and held until the call ends, and the parts are built off the event loop; (7) when the Decisions classifier applies, its request, the second resolve, and the gate with `preset_accepts` again on the final route whenever the call carries kinds or the route changed; (8) the project, the upstream call and the usage event

#### Scenario: The order in chat send
- **WHEN** `perplexity_chat` `send` runs
- **THEN** steps (1) to (3) are as in ask with no database access; (4) the files are read and the byte share acquired, before the chat is loaded, because the kinds the route must carry depend on the stored notes; (5) the chat and its stored attachment notes are loaded (an unknown chat is `not_found`) and the per-chat document limits checked; (6) the real `resolve` with `new_kinds | inherited_kinds` (a replay: `new_kinds` only); (7) the gate, then as for ask the Decisions request, the second resolve and the final gate; (8) the project, the upstream call, the usage event and the chat write; a call the gate refuses has already read up to 32 MiB, and nothing is sent or recorded for it

#### Scenario: A bad attachment beats the classifier
- **WHEN** a dynamic-mode call with the Decisions classifier carries an unreadable attachment
- **THEN** it fails with `invalid_request` before any Decisions request is made

#### Scenario: A tier error beats attachment reads
- **WHEN** a call names an unknown `tier` and an attachment path
- **THEN** it fails on the tier and the file is never opened

#### Scenario: Nothing can take the kinds
- **WHEN** a dynamic-mode call with the Decisions classifier, no selector and tier pins that all name models recorded as refusing images carries a PNG
- **THEN** the call fails with `invalid_request` and no Decisions request is made

#### Scenario: A reclassified tier whose pin refuses
- **WHEN** the Decisions classifier raises the tier and the pinned model of that tier is recorded as refusing the call's kinds
- **THEN** the second gate fails the call with `invalid_request` naming the pinned model and the kind, and no model request is made

#### Scenario: An explicit model needs no classifier
- **WHEN** a call names a `model` that refuses the kinds
- **THEN** the gate fails the call at step (5), before any file is read


# agent-ask Specification

## ADDED Requirements

### Requirement: Ask takes attachments
`perplexity_ask` SHALL accept the optional `attachments` of `media-attachments`. The query stays required and an attachment never replaces it. A call with no `attachments`, or an empty list, SHALL build the request it built before this change. The parameter is a list of strings with one description, and its sentence in the tool description is at most 100 characters.

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
In ask and chat `send` the steps SHALL run in this order and each failure stops the call: selector and tier errors, attachment parsing, provisional resolve and option validation, the real `resolve` with the required kinds, the gate, the Decisions request, the second resolve, then the gate and `preset_accepts` again on the final route, and only then the project. Nothing before the project step stores or spends anything.

#### Scenario: A bad attachment beats the classifier
- **WHEN** a dynamic-mode call with the Decisions classifier carries an unreadable attachment
- **THEN** it fails with `invalid_request` before any Decisions request is made

#### Scenario: A tier error beats attachment reads
- **WHEN** a call names an unknown `tier` and an attachment path
- **THEN** it fails on the tier and the file is never opened


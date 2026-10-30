# model-catalog Specification

## ADDED Requirements

### Requirement: The model list reports each model's inputs
`perplexity_models` SHALL give each listed model its inputs as ONE short string field (for example `image,document` or `image (refused document)`, empty when unknown) and the same in its text table, and SHALL NOT add an object, a per-kind field or a matrix-section count to the output schema (the count of models with unknown inputs appears in the text only). A model not in the matrix SHALL be listed with the empty string.

#### Scenario: Inputs shown
- **WHEN** a client calls `perplexity_models` against a server whose matrix records `perplexity/deepseek-v4-pro-0813` as refusing images and accepting documents
- **THEN** that model's inputs string reads `document (refused image)`

#### Scenario: A model the matrix lacks
- **WHEN** the live list holds an id the matrix does not hold
- **THEN** its inputs string is empty

### Requirement: The inputs field costs few schema bytes
The output schema's added field SHALL have a description of at most 30 characters and add at most 120 bytes to the `tools/list` response. The tool text SHALL say that audio and video are not accepted by the API and that an empty inputs string means unknown, not unsupported. For 54 models the added inputs SHALL grow the structured content by at most 1700 bytes and the text table by at most 1800 bytes (measured, recorded in the acceptance notes).

#### Scenario: Schema growth
- **WHEN** the tools list is measured before and after the field is added
- **THEN** the difference attributable to the field is at most 120 bytes

#### Scenario: Output size
- **WHEN** a call lists 54 models
- **THEN** the structured content grows by at most 1700 bytes and the text table by at most 1800

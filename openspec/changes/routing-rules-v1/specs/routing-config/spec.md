# Spec Delta

## MODIFIED Requirements

### Requirement: Routing mode
The server SHALL read `PERPLEXITY_ROUTING` (case-insensitive), one of `standard` (the default), `custom` and `dynamic`, and apply it to `perplexity_ask` and to `perplexity_chat` send. `perplexity_research` SHALL be unchanged in every mode, because its depths are presets and not models. An unknown value SHALL fail startup naming the variable and the three accepted values.

#### Scenario: Default mode
- **WHEN** the server starts with only the API key set
- **THEN** the routing mode is `standard`

#### Scenario: Unknown mode
- **WHEN** the server starts with `PERPLEXITY_ROUTING=auto`
- **THEN** startup fails naming `PERPLEXITY_ROUTING`, the value `auto` and the accepted values `standard`, `custom` and `dynamic`

#### Scenario: Research is unaffected
- **WHEN** `perplexity_research` is called in `custom` or `dynamic` mode
- **THEN** its request names a preset exactly as before and carries no routing

### Requirement: The tier argument
`perplexity_ask` and `perplexity_chat` send SHALL accept `tier`, one of `light`, `standard` and `complex`, valid only in `custom` and `dynamic` mode. In any other mode it SHALL fail with `invalid_request` naming `tier` and the active mode, and nothing is sent. A value outside the three SHALL fail with `invalid_request` naming `tier`.

#### Scenario: Tier in custom mode
- **WHEN** an ask in `custom` mode names `tier` `complex`
- **THEN** the request names the `complex` tier's model

#### Scenario: Tier in dynamic mode
- **WHEN** an ask in `dynamic` mode names `tier` `light`
- **THEN** the `light` tier runs, the text is not classified and `selected_by` is `tier`

#### Scenario: Tier in standard mode
- **WHEN** an ask in `standard` mode names `tier` `light`
- **THEN** the call fails with `invalid_request` naming `tier` and the mode `standard`, and no request reaches the API

#### Scenario: Unknown tier
- **WHEN** an ask in `custom` mode names `tier` `huge`
- **THEN** the call fails with `invalid_request` naming `tier`

### Requirement: Resolution order
For one call the server SHALL resolve the model by the one selector the call names and report which rule applied in `selected_by`: an explicit `model` (`model`), an explicit `depth` (`depth`, the preset of that name), an explicit `tier` (`tier`), or, when the call names none, the mode's default (`default`: the model of `standard` mode, or the `standard` tier in `custom` mode) or, in `dynamic` mode, the tier the rules classifier picks (`rules`).

#### Scenario: Depth still selects a preset
- **WHEN** an ask in any mode names `depth` `medium`
- **THEN** the request names preset `medium` and no model, and the reported `selected_by` is `depth`

#### Scenario: Explicit model wins over the mode
- **WHEN** an ask in `custom` mode names `model` `openai/gpt-6-luna`
- **THEN** the request names that model and the reported `selected_by` is `model`

#### Scenario: Explicit model wins in dynamic mode
- **WHEN** an ask in `dynamic` mode names `model` `openai/gpt-6-luna`
- **THEN** the request names that model, nothing is classified and the reported `selected_by` is `model`

#### Scenario: Chat send follows the same rules
- **WHEN** `perplexity_chat` send is called in `custom` mode with `tier` `light`
- **THEN** the request names the `light` tier's model, and the next turn of the same chat may name a different tier

### Requirement: Every ask and chat result reports its routing
`perplexity_ask` and `perplexity_chat` send SHALL return a `routing` object with `mode`, `tier` (null unless a tier was used, the `custom` default applied or the rules picked one), `model` (the id requested, or null when a preset was named), `selected_by` (`default`, `tier`, `depth`, `model` or `rules`) and `reason` (a short text, set only when `selected_by` is `rules`), so the caller sees what happened to its call without having been told the configuration.

#### Scenario: Custom default
- **WHEN** an ask names nothing in `custom` mode
- **THEN** the routing is mode `custom` (the mode) and tier `standard` (the `standard` tier, not the `standard` mode), model the `standard` tier's id, `selected_by` `default`

#### Scenario: Default call
- **WHEN** an ask names nothing in `standard` mode
- **THEN** the result's routing is mode `standard`, tier null, model `perplexity/sonar`, `selected_by` `default`

#### Scenario: Tier call
- **WHEN** an ask in `custom` mode names `tier` `light`
- **THEN** the routing is mode `custom`, tier `light`, the light model's id and `selected_by` `tier`

#### Scenario: Depth call
- **WHEN** an ask names `depth` `low`
- **THEN** the routing carries `selected_by` `depth` and model null

#### Scenario: Rules call
- **WHEN** an ask in `dynamic` mode names nothing and the rules pick `light`
- **THEN** the routing is mode `dynamic`, tier `light`, preset `fast` with model null, `selected_by` `rules` and a non-empty `reason`

## REMOVED Requirements

### Requirement: Dynamic mode is reserved
**Reason**: Dynamic mode now ships, resolving by the rules classifier of `routing-rules`.
**Migration**: A server started with `PERPLEXITY_ROUTING=dynamic` now starts. Nothing to change for the other modes; the startup refusal message is gone.

## ADDED Requirements

### Requirement: Dynamic mode routes by rules
In `dynamic` mode a call that names no `depth`, `tier` or `model` SHALL be classified by the rules of `routing-rules` over the call's text (the ask's query, the chat send's message) and run the tier the classification names. The classification makes no upstream request.

#### Scenario: A lookup goes light
- **WHEN** an ask in `dynamic` mode asks `What is the latest stable Python release?`
- **THEN** the request names preset `fast`, and the routing is tier `light` with `selected_by` `rules`

#### Scenario: A long analysis goes complex
- **WHEN** an ask in `dynamic` mode asks to compare two designs and evaluate their trade-offs
- **THEN** the request names preset `medium` and the routing tier is `complex`

### Requirement: Dynamic tiers need no configuration
In `dynamic` mode the `light` tier SHALL run preset `fast`, the `standard` tier SHALL run `PERPLEXITY_MODEL` (default `perplexity/sonar`) and the `complex` tier SHALL run preset `medium`. `PERPLEXITY_TIER_LIGHT`, `PERPLEXITY_TIER_STANDARD` and `PERPLEXITY_TIER_COMPLEX`, each optional and validated as a model id when set, SHALL replace the tier's default with that model. Presets `high` and `xhigh` SHALL never be selected by dynamic mode.

#### Scenario: Nothing configured
- **WHEN** the server starts in `dynamic` mode with only the API key set
- **THEN** it starts, and the three tiers run `fast`, `perplexity/sonar` and `medium`

#### Scenario: A tier replaced
- **WHEN** `PERPLEXITY_TIER_COMPLEX` is `anthropic/claude-opus-5-5` and the rules pick `complex`
- **THEN** the request names that model and no preset

#### Scenario: A bad tier variable
- **WHEN** `PERPLEXITY_TIER_LIGHT` holds a value that is not a plain model id
- **THEN** startup fails naming `PERPLEXITY_TIER_LIGHT`

### Requirement: A chat follow-up holds its tier
In `dynamic` mode a `perplexity_chat` send to an existing chat that names no selector SHALL route to the higher of the tier the rules pick for the new message and the tier of the chat's previous assistant turn, recovered by matching that turn's stored preset or model against the three tiers (a model that matches none counts as `standard`). It SHALL NOT route below the previous tier.

#### Scenario: A short follow-up to a complex chat
- **WHEN** a chat's first turn ran the `complex` tier and the next message is `and in 2025?`
- **THEN** the second turn runs the `complex` tier, with `selected_by` `rules`

#### Scenario: A longer question raises the tier
- **WHEN** a chat's first turn ran `light` and the next message classifies `complex`
- **THEN** the second turn runs the `complex` tier

#### Scenario: Explicit selectors still win
- **WHEN** a follow-up names `depth` `fast`
- **THEN** it runs preset `fast` with `selected_by` `depth`, whatever tier the chat last used

### Requirement: Dynamic mode is told to the calling agent
The MCP `instructions` and the `perplexity_ask` and `perplexity_chat` description sentence SHALL, in `dynamic` mode, state the mode, that the server picks a tier from the prompt when a call names nothing, what each tier runs, and that `tier`, `depth` or `model` overrides the choice. Both SHALL be pure functions of the settings, with no secret.

#### Scenario: Dynamic instructions
- **WHEN** a client initializes against a `dynamic` server
- **THEN** the instructions name mode `dynamic`, the three tiers with what each runs, and say a named `tier`, `depth` or `model` overrides the server's choice

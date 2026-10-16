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
For one call the server SHALL resolve the model by the one selector the call names and report which rule applied in `selected_by`: an explicit `model` (`model`), an explicit `depth` (`depth`, the preset of that name), an explicit `tier` (`tier`), or, when the call names none, the mode's default (`default`: the model of `standard` mode, or the `standard` tier in `custom` mode) or, in `dynamic` mode, the tier the dynamic classifier picks (`classifier`).

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
`perplexity_ask` and `perplexity_chat` send SHALL return a `routing` object with `mode`, `tier` (null unless a tier was used, the `custom` default applied or dynamic mode picked one), `model` (the id requested, or null when a preset was named), `selected_by` (`default`, `tier`, `depth`, `model` or `classifier`), `classifier` (the classifier that decided, `rules` unless another is configured, when `selected_by` is `classifier`; otherwise null) and `reason` (a short text, set when dynamic mode routed the call: by a classifier, by the follow-up floor or because search is off), so the caller sees what happened to its call without having been told the configuration.

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
- **THEN** the routing is mode `dynamic`, tier `light`, the request names preset `fast` and the routing's model is null, `selected_by` is `classifier`, `classifier` is `rules` and `reason` is non-empty

### Requirement: Refusal order
A call that breaks more than one routing rule SHALL be refused with the first of these that applies: a conflict between selectors, then `tier` outside `custom` and `dynamic`, then an unknown `tier`, then `depth` `high` or `xhigh`, so the message an agent reads is deterministic. In `dynamic` mode the selector-conflict message SHALL say that, with nothing named, the server picks the tier from the prompt.

#### Scenario: Two rules broken at once
- **WHEN** an ask in `standard` mode names `tier` `light` and `depth` `low`
- **THEN** the call fails with the selector-conflict message naming `tier` and `depth`, not the message about `tier` outside `custom` and `dynamic`

#### Scenario: Conflict in dynamic mode
- **WHEN** an ask in `dynamic` mode names `tier` and `model`
- **THEN** the message names both, says to pass one or neither, and says that with neither the tier is picked from the prompt

### Requirement: A routed call is shaped like an explicit model call
A call resolved to a model by the mode's default, by `tier` or by the rules SHALL be shaped exactly as an explicit `model` call is: the web search tool, the step budget, `search` false allowed and the `anthropic/` default output cap. A call resolved to a preset by the rules SHALL be shaped exactly as a call naming that `depth` is. `agent-ask` owns those rules; this requirement only says they apply to routed calls.

#### Scenario: Default route is shaped like an explicit model
- **WHEN** an ask names nothing in `standard` mode
- **THEN** the request carries the web search tool and the step budget of an explicit-model request

#### Scenario: Anthropic tier gets the output cap
- **WHEN** an ask in `custom` mode resolves to a tier model whose id starts with `anthropic/`
- **THEN** the request carries the same default output cap as an explicit `anthropic/` model

#### Scenario: A rules preset is shaped like a depth call
- **WHEN** an ask in `dynamic` mode is routed by the rules to preset `fast`
- **THEN** its request equals the request of the same ask naming `depth` `fast`

### Requirement: The mode is a default, never a restriction
The routing mode and its models SHALL only supply what a call does not choose for itself. An explicit `model` on `perplexity_ask` or `perplexity_chat` send SHALL be used exactly as given in every mode, whether or not it is the configured model, one of the tiers or listed in the live catalog, and a call that names no `model` (and no `depth` or `tier`) SHALL fall back to the mode's default route. No mode SHALL refuse, rewrite or second-guess an explicit model.

#### Scenario: Explicit model in standard mode
- **WHEN** `PERPLEXITY_MODEL` is `perplexity/sonar` and an ask names `model` `anthropic/claude-opus-5-5`
- **THEN** the request names `anthropic/claude-opus-5-5`, and the result's routing is model `anthropic/claude-opus-5-5` with `selected_by` `model`

#### Scenario: Explicit model that is not a tier
- **WHEN** the mode is `custom` and a chat send names a `model` that none of the three tiers uses
- **THEN** the request names that model

#### Scenario: Explicit model the catalog does not list
- **WHEN** an ask names a `model` the live catalog does not list
- **THEN** the call is sent with it and any refusal comes from the API, as an upstream error

#### Scenario: No model falls back to the default
- **WHEN** an ask or chat send names no `model`, `depth` or `tier`
- **THEN** the request names the mode's default route: the default model in `standard` and `custom` mode, the tier the dynamic classifier picks in `dynamic` mode

### Requirement: The instructions text
The MCP `instructions` SHALL be rendered at startup from the settings and state the mode, the standard model or the three tiers with what each runs (a model id or a preset), when to pass `tier`, `depth` or `model`, that `high` and `xhigh` belong to `perplexity_research`, and that `perplexity_help` explains the tools. It SHALL hold no secret and not change during the process. `perplexity_help` repeats the mode but is a pointer, not a fifth channel of "The calling agent is told the configuration".

#### Scenario: Standard instructions
- **WHEN** a client initializes against a `standard` server
- **THEN** the instructions name the mode `standard` and the standard model, and do not mention tiers as usable

#### Scenario: Custom instructions
- **WHEN** a client initializes against a `custom` server
- **THEN** the instructions list `light`, `standard` and `complex` with their model ids and say that `tier` selects one

#### Scenario: Instructions point to help
- **WHEN** a client initializes against any server
- **THEN** the instructions name `perplexity_help`

## REMOVED Requirements

### Requirement: Dynamic mode is reserved
**Reason**: Dynamic mode now ships, resolving by the rules classifier of `routing-rules`.
**Migration**: A server started with `PERPLEXITY_ROUTING=dynamic` now starts. Nothing to change for the other modes; the startup refusal message is gone.

## ADDED Requirements
### Requirement: Dynamic mode needs a model when search is off
In `dynamic` mode a call with `search` false that names no selector SHALL run the `standard` tier's model without classification (a preset always searches), with tier `standard`, `selected_by` `default`, `classifier` null and a reason saying search is off. With an explicit `tier` that runs a preset it SHALL fail with `invalid_request` naming `tier` and `search`. Search filters stay allowed on a preset route, as with `depth`.

#### Scenario: Search off
- **WHEN** an ask in `dynamic` mode with `search` false has a lookup-shaped query
- **THEN** the request names the standard tier's model, carries no tools and does not fail, and the routing reason says search is off

#### Scenario: Search off with a preset tier named
- **WHEN** an ask in `dynamic` mode names `tier` `light` (preset `fast`) and `search` false
- **THEN** the call fails with `invalid_request` naming `tier` and `search`, says a preset always searches and to pass `model`, tier `standard` or search true, and nothing is sent

### Requirement: Dynamic mode warns about a shadowed model variable
In `dynamic` mode the server SHALL log one warning naming `PERPLEXITY_MODEL` when both it and `PERPLEXITY_TIER_STANDARD` are set, because the tier variable replaces it. No other variable is ignored in `dynamic` mode.

#### Scenario: Both set
- **WHEN** the server starts in `dynamic` mode with `PERPLEXITY_MODEL` and `PERPLEXITY_TIER_STANDARD` set
- **THEN** it starts and logs one warning naming `PERPLEXITY_MODEL`

### Requirement: Dynamic mode routes by rules
In `dynamic` mode a call that names no `depth`, `tier` or `model` SHALL be classified over the call's text (the ask's query, the chat send's message) by the configured classifier, the rules of `routing-rules` unless a change adds another, and run the tier the classification names. With the rules classifier the classification makes no upstream request.

#### Scenario: A lookup goes light
- **WHEN** an ask in `dynamic` mode asks `What is the latest stable Python release?`
- **THEN** the request names preset `fast`, and the routing is tier `light` with `selected_by` `classifier` and `classifier` `rules`

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
In `dynamic` mode a `perplexity_chat` send to an existing chat that names no selector SHALL route to the higher of the tier the dynamic classifier picks for the new message and the tier of the chat's previous assistant turn. It SHALL NOT route below that tier, and when that tier is higher than the classifier's pick the routing reason SHALL say the tier was held.

#### Scenario: Previous tier from the stored turn
- **WHEN** the previous assistant turn stored preset `medium`, or no preset and the model of a replaced tier
- **THEN** its tier is the one whose preset or model matches, the highest tier winning a tie, and `standard` when none matches

### Requirement: A chat follow-up's previous tier is recovered from storage
The previous turn's tier SHALL be found by matching that turn's stored preset, else its stored model, against the three tiers' routes (a tier replaced by a `PERPLEXITY_TIER_*` model matches by model only), the highest tier winning a tie and no match counting as `standard`.

#### Scenario: A model that matches no tier
- **WHEN** the previous turn ran an explicit model that no tier uses
- **THEN** its tier counts as `standard`

#### Scenario: A short follow-up to a complex chat
- **WHEN** a chat's first turn ran the `complex` tier and the next message is `and in 2025?`
- **THEN** the second turn runs the `complex` tier with `selected_by` `classifier` and a reason saying it was held at `complex`

#### Scenario: A longer question raises the tier
- **WHEN** a chat's first turn ran `light` and the next message classifies `complex`
- **THEN** the second turn runs the `complex` tier

#### Scenario: Explicit selectors still win
- **WHEN** a follow-up names `depth` `fast`
- **THEN** it runs preset `fast` with `selected_by` `depth`, whatever tier the chat last used

#### Scenario: Errors keep their order
- **WHEN** a nameless follow-up in `dynamic` mode names a chat that does not exist, or a send names an invalid selector
- **THEN** the call fails with `not_found` for the chat, and with `invalid_request` for the selector or any other invalid option before the chat is looked up, as in the other modes

### Requirement: Dynamic mode is told to the calling agent
The MCP `instructions` and the `perplexity_ask` and `perplexity_chat` description sentence SHALL, in `dynamic` mode, state the mode, that the server picks a tier from the prompt when a call names nothing, what each tier runs, and that `tier`, `depth` or `model` overrides the choice. Both SHALL be pure functions of the settings, with no secret.

#### Scenario: Dynamic instructions
- **WHEN** a client initializes against a `dynamic` server
- **THEN** the instructions name mode `dynamic`, the three tiers with what each runs, and say a named `tier`, `depth` or `model` overrides the server's choice

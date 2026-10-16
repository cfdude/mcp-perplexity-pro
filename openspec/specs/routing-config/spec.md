# routing-config Specification

## Purpose
Defines which model answers `perplexity_ask` and `perplexity_chat` send: the routing mode (`standard`, `custom`, `dynamic`), the `tier`, `depth` and `model` selectors and their order and conflicts, the rule that an explicit model is always used as given, the `routing` object every result carries, and the instructions text that tells the calling agent the configuration.

## Requirements

### Requirement: Routing mode
The server SHALL read `PERPLEXITY_ROUTING` (case-insensitive), one of `standard` (the default), `custom` and `dynamic`, and apply it to `perplexity_ask` and to `perplexity_chat` send. `perplexity_research` SHALL be unchanged in every mode, because its depths are presets and not models. An unknown value SHALL fail startup naming the variable and the three accepted values.

#### Scenario: Default mode
- **WHEN** the server starts with only the API key set
- **THEN** the routing mode is `standard`

#### Scenario: Unknown mode
- **WHEN** the server starts with `PERPLEXITY_ROUTING=auto`
- **THEN** startup fails naming `PERPLEXITY_ROUTING`, the value `auto` and the accepted values `standard` and `custom`, and says `dynamic` is reserved and not available yet

#### Scenario: Research is unaffected
- **WHEN** `perplexity_research` is called in `custom` mode
- **THEN** its request names a preset exactly as before and carries no routing

### Requirement: Dynamic mode is reserved
`dynamic` SHALL fail startup with a message naming `PERPLEXITY_ROUTING` and saying the dynamic classifier is not available in this version, until a change ships it, so the three-way choice is documented once and keeps its shape.

#### Scenario: Dynamic is reserved
- **WHEN** the server starts with `PERPLEXITY_ROUTING=dynamic`
- **THEN** startup fails, before any connection is accepted, with a message naming `PERPLEXITY_ROUTING` and stating that dynamic routing is not available yet

### Requirement: Standard mode uses one configurable model
In `standard` mode the server SHALL use `PERPLEXITY_MODEL`, default `perplexity/sonar`, for any call that names no `depth`, `tier` or `model`.

#### Scenario: Default model
- **WHEN** an ask names no depth, tier or model in `standard` mode with `PERPLEXITY_MODEL` unset
- **THEN** the request names model `perplexity/sonar` and no preset, grounded with the web search tool as an explicit model is

#### Scenario: Configured model
- **WHEN** `PERPLEXITY_MODEL` is `anthropic/claude-sonnet-5-5` and an ask names nothing
- **THEN** the request names that model

### Requirement: Model ids are plain and unused variables are ignored
Each configured model id (`PERPLEXITY_MODEL` and the three tier variables) SHALL be a string of 1 to 200 characters drawn from letters, digits and `.` `_` `:` `/` `@` `+` `-`, because it is written into the instructions text the agent reads (no whitespace, control, invisible or Markdown characters); anything else fails startup naming the variable. A variable the active mode does not use SHALL be ignored and not validated.

#### Scenario: Blank model
- **WHEN** `PERPLEXITY_MODEL` is set to an empty string, to 300 characters or to a value containing a newline or a zero-width space
- **THEN** startup fails naming `PERPLEXITY_MODEL`

### Requirement: Custom mode has three required tiers
In `custom` mode the server SHALL require `PERPLEXITY_TIER_LIGHT`, `PERPLEXITY_TIER_STANDARD` and `PERPLEXITY_TIER_COMPLEX`, each a model id valid as above, and fail startup naming every variable that is missing or invalid. A call with no `depth`, `tier` or `model` SHALL use the `standard` tier. The three tiers are for light or agent-execution work, everyday work and work needing deeper reasoning.

#### Scenario: Tiers present
- **WHEN** the mode is `custom` with all three tier variables set
- **THEN** the server starts and `tier` `light`, `standard` and `complex` resolve to the three configured models

#### Scenario: A tier missing
- **WHEN** the mode is `custom` and `PERPLEXITY_TIER_COMPLEX` is unset
- **THEN** startup fails with a message naming `PERPLEXITY_TIER_COMPLEX`

#### Scenario: Default tier
- **WHEN** an ask names nothing in `custom` mode
- **THEN** the request names the model of the `standard` tier

#### Scenario: Unused tier variables
- **WHEN** the mode is `standard` and a tier variable is set
- **THEN** the server starts, ignores it and logs one warning naming the variable

#### Scenario: Unused variable is not validated
- **WHEN** the mode is `standard` and `PERPLEXITY_TIER_LIGHT` is set to an empty string
- **THEN** the server starts and logs one warning naming the variable

#### Scenario: Unused model variable
- **WHEN** the mode is `custom` and `PERPLEXITY_MODEL` is set
- **THEN** the server starts, ignores it and logs one warning naming the variable

### Requirement: The tier argument
`perplexity_ask` and `perplexity_chat` send SHALL accept `tier`, one of `light`, `standard` and `complex`, valid only in `custom` mode (and later in `dynamic`). In any other mode it SHALL fail with `invalid_request` naming `tier` and the active mode, and nothing is sent. A value outside the three SHALL fail with `invalid_request` naming `tier`.

#### Scenario: Tier in custom mode
- **WHEN** an ask in `custom` mode names `tier` `complex`
- **THEN** the request names the `complex` tier's model

#### Scenario: Tier in standard mode
- **WHEN** an ask in `standard` mode names `tier` `light`
- **THEN** the call fails with `invalid_request` naming `tier` and the mode `standard`, and no request reaches the API

#### Scenario: Unknown tier
- **WHEN** an ask in `custom` mode names `tier` `huge`
- **THEN** the call fails with `invalid_request` naming `tier`

### Requirement: A routed call is shaped like an explicit model call
A call resolved to a model by the mode's default or by `tier` SHALL be shaped exactly as an explicit `model` call is: the web search tool, the step budget, `search` false allowed and the `anthropic/` default output cap. `agent-ask` owns those rules; this requirement only says they apply to routed calls.

#### Scenario: Default route is shaped like an explicit model
- **WHEN** an ask names nothing in `standard` mode
- **THEN** the request carries the web search tool and the step budget of an explicit-model request

#### Scenario: Anthropic tier gets the output cap
- **WHEN** an ask in `custom` mode resolves to a tier model whose id starts with `anthropic/`
- **THEN** the request carries the same default output cap as an explicit `anthropic/` model

### Requirement: The mode is a default, never a restriction
The routing mode and its models SHALL only supply what a call does not choose for itself. An explicit `model` on `perplexity_ask` or `perplexity_chat` send SHALL be used exactly as given in every mode, whether or not it is the configured model, one of the tiers or listed in the live catalog, and a call that names no `model` (and no `depth` or `tier`) SHALL fall back to the mode's default. No mode SHALL refuse, rewrite or second-guess an explicit model.

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
- **THEN** the request names the mode's default model

### Requirement: Resolution order
For one call the server SHALL resolve the model by the one selector the call names and report which rule applied in `selected_by`: an explicit `model` (`model`), an explicit `depth` (`depth`, the preset of that name), an explicit `tier` (`tier`), or, when the call names none, the mode's default (`default`: the model of `standard` mode, or the `standard` tier in `custom` mode).

#### Scenario: Depth still selects a preset
- **WHEN** an ask in any mode names `depth` `medium`
- **THEN** the request names preset `medium` and no model, and the reported `selected_by` is `depth`

#### Scenario: Explicit model wins over the mode
- **WHEN** an ask in `custom` mode names `model` `openai/gpt-6-luna`
- **THEN** the request names that model and the reported `selected_by` is `model`

#### Scenario: Chat send follows the same rules
- **WHEN** `perplexity_chat` send is called in `custom` mode with `tier` `light`
- **THEN** the request names the `light` tier's model, and the next turn of the same chat may name a different tier

### Requirement: Refusal order
A call that breaks more than one routing rule SHALL be refused with the first of these that applies: a conflict between selectors, then `tier` outside `custom`, then an unknown `tier`, then `depth` `high` or `xhigh`, so the message an agent reads is deterministic.

#### Scenario: Two rules broken at once
- **WHEN** an ask in `standard` mode names `tier` `light` and `depth` `low`
- **THEN** the call fails with the selector-conflict message naming `tier` and `depth`, not the message about `tier` outside `custom`

### Requirement: Selectors are mutually exclusive
`depth` together with `model`, `depth` together with `tier`, and `model` together with `tier` SHALL fail with `invalid_request`, and nothing is sent. The message is written for the calling agent: it names both options given, says each picks the model on its own so the two cannot be combined, and tells the agent what to do (pass only one, or none to use the mode's default). This requirement owns those conflicts; the ask requirements refer to it.

#### Scenario: Conflicting selectors
- **WHEN** an ask names `tier` and `depth`, or `tier` and `model`
- **THEN** the call fails with `invalid_request` naming both options and no request reaches the API

#### Scenario: The refusal tells the agent how to fix the call
- **WHEN** an ask names `tier` `light` and `model` `openai/gpt-6-luna`
- **THEN** the message names `tier` and `model`, says they cannot be used together because each selects the model, and says to pass one of them or neither

### Requirement: Every ask and chat result reports its routing
`perplexity_ask` and `perplexity_chat` send SHALL return a `routing` object with `mode`, `tier` (null unless a tier was used or the `custom` default applied), `model` (the id requested, or null when a preset was named) and `selected_by` (`default`, `tier`, `depth` or `model`), so the caller sees what happened to its call without having been told the configuration.

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

### Requirement: The calling agent is told the configuration
The server SHALL give the calling agent the active mode and what it resolves to through four channels, so that a client ignoring one still learns it from another: the MCP `instructions` text, the `perplexity_ask` and `perplexity_chat` descriptions (one sentence stating the mode and the default), the `routing` field above and the `perplexity_models` section.

#### Scenario: A client that ignores instructions
- **WHEN** a client never reads the instructions
- **THEN** the tool descriptions and the first result's `routing` still show the mode and the model used

### Requirement: The instructions text
The MCP `instructions` SHALL be rendered at startup from the settings and state the mode, the standard model or the three tiers with their model ids, when to pass `tier`, `depth` or `model`, that depth `high` and `xhigh` belong to `perplexity_research`, and that `perplexity_help` explains the tools. The text SHALL contain no secret and SHALL be identical for the life of the process. `perplexity_help` repeats the routing mode but is a pointer and a topic, not a fifth channel of "The calling agent is told the configuration".

#### Scenario: Standard instructions
- **WHEN** a client initializes against a `standard` server
- **THEN** the instructions name the mode `standard` and the standard model, and do not mention tiers as usable

#### Scenario: Custom instructions
- **WHEN** a client initializes against a `custom` server
- **THEN** the instructions list `light`, `standard` and `complex` with their model ids and say that `tier` selects one

#### Scenario: Instructions point to help
- **WHEN** a client initializes against any server
- **THEN** the instructions name `perplexity_help`

### Requirement: Usage records the resolved model
The usage event of a routed call SHALL record the model the API reports, as it does today, and SHALL NOT change the usage schema; routing adds no migration. A call that ran a model route SHALL record and report preset null: no code path SHALL fall back to a default preset name.

#### Scenario: Default call is recorded
- **WHEN** an ask in `standard` mode completes
- **THEN** one usage event exists whose model is the one the response reports

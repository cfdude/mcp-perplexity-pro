# Spec Delta

## MODIFIED Requirements

### Requirement: Routing mode
The server SHALL read `PERPLEXITY_ROUTING` (case-insensitive), one of `standard` (the default), `custom` and `dynamic`, and apply it to `perplexity_ask`, to `perplexity_chat` send and, in `dynamic` mode only, to `perplexity_research` when it names no `depth`. In `standard` and `custom` mode `perplexity_research` SHALL be unchanged, because its depths are presets and not models. An unknown value SHALL fail startup naming the variable and the three accepted values.

#### Scenario: Default mode
- **WHEN** the server starts with only the API key set
- **THEN** the routing mode is `standard`

#### Scenario: Unknown mode
- **WHEN** the server starts with `PERPLEXITY_ROUTING=auto`
- **THEN** startup fails naming `PERPLEXITY_ROUTING`, the value `auto` and the accepted values `standard`, `custom` and `dynamic`

#### Scenario: Research is unaffected
- **WHEN** `perplexity_research` is called in `standard` or `custom` mode
- **THEN** its request names a preset exactly as before and carries no routing

### Requirement: A routed call is shaped like an explicit model call
A call resolved to a model by the mode's default, by `tier`, by a pin or by the router SHALL be shaped exactly as an explicit `model` call is: the web search tool, the step budget, `search` false allowed and the `anthropic/` default output cap, plus the reasoning effort the router chose when it chose one. A call resolved to a preset by the router's last fallback rung SHALL be shaped exactly as a call naming that `depth` is. `agent-ask` owns those rules; this requirement only says they apply to routed calls.

#### Scenario: Default route is shaped like an explicit model
- **WHEN** an ask names nothing in `standard` mode
- **THEN** the request carries the web search tool and the step budget of an explicit-model request

#### Scenario: Anthropic tier gets the output cap
- **WHEN** an ask in `custom` mode resolves to a tier model whose id starts with `anthropic/`
- **THEN** the request carries the same default output cap as an explicit `anthropic/` model

#### Scenario: A router model route carries the effort
- **WHEN** an ask in `dynamic` mode is routed to a model with effort `medium`
- **THEN** its request names the model, carries the web search tool, the step budget of an explicit-model request and `reasoning.effort` `medium`

#### Scenario: A classifier preset is shaped like a depth call
- **WHEN** an ask in `dynamic` mode reaches the documented-preset fallback rung for preset `fast`
- **THEN** its request equals the request of the same ask naming `depth` `fast`

### Requirement: Resolution order
For one call the server SHALL resolve the model by the one selector the call names and report which rule applied in `selected_by`: an explicit `model` (`model`), an explicit `depth` (`depth`, the preset of that name), an explicit `tier` (`tier`), or, when the call names none, the mode's default (`default`: the `standard` mode model, or the `custom` mode `standard` tier) or, in `dynamic` mode, the router's evidence-based choice (`router`) or its fallback (`fallback`). A `PERPLEXITY_TIER_*` pin applied in `dynamic` mode SHALL be reported as `router` when the classifier picked its tier and as `tier` when the caller named it, in both cases with the reason `pinned`.

#### Scenario: Depth still selects a preset
- **WHEN** an ask in any mode names `depth` `medium`
- **THEN** the request names preset `medium` and no model, and the reported `selected_by` is `depth`

#### Scenario: Explicit model wins over the mode
- **WHEN** an ask in `custom` mode names `model` `openai/gpt-6-luna`
- **THEN** the request names that model and the reported `selected_by` is `model`

#### Scenario: Explicit model wins in dynamic mode
- **WHEN** an ask in `dynamic` mode names `model` `openai/gpt-6-luna`
- **THEN** the request names that model, nothing is classified or routed, no reasoning effort is sent and the reported `selected_by` is `model`

#### Scenario: Chat send follows the same rules
- **WHEN** `perplexity_chat` send is called in `custom` mode with `tier` `light`
- **THEN** the request names the `light` tier's model, and the next turn of the same chat may name a different tier

### Requirement: The mode is a default, never a restriction
The routing mode and its models SHALL only supply what a call does not choose for itself. An explicit `model` on `perplexity_ask` or `perplexity_chat` send SHALL be used exactly as given in every mode, whether or not it is the configured model, one of the tiers or listed in the live catalog, and a call that names no `model` (and no `depth` or `tier`) SHALL fall back to the mode's default route. No mode SHALL refuse, rewrite or second-guess an explicit model, except the attachment gate of `media-attachments`: `no` refuses and `unknown` is sent for an explicit model, a pin, a tier model or the default route, while a held or routed model needs `yes`.

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
- **THEN** the request names the mode's default route: the default model in `standard` and `custom` mode, the router's choice in `dynamic` mode

### Requirement: Refusal order
A call that breaks more than one routing rule SHALL be refused with the first of these that applies: a conflict between selectors, then `tier` outside `custom` and `dynamic`, then an unknown `tier`, then `depth` `high` or `xhigh`, so the message an agent reads is deterministic. In `dynamic` mode the selector-conflict message SHALL say that, with nothing named, the server picks the model and effort from the prompt.

#### Scenario: Two rules broken at once
- **WHEN** an ask in `standard` mode names `tier` `light` and `depth` `low`
- **THEN** the call fails with the selector-conflict message naming `tier` and `depth`, not the message about `tier` outside `custom` and `dynamic`

#### Scenario: Conflict in dynamic mode
- **WHEN** an ask in `dynamic` mode names `tier` and `model`
- **THEN** the message names both, says to pass one or neither, and says that with neither the model and effort are picked from the prompt

### Requirement: Dynamic mode routes by a classifier
In `dynamic` mode a call that names no `depth`, `tier` or `model` SHALL be classified over the call's text (the ask's query, the chat send's message, the research query) by the configured classifier, the rules of `routing-rules` unless a change adds another, which supplies the tier; the task class SHALL always come from the rules, offline. The router of `routing-evidence` SHALL then choose the model and the effort. With the rules classifier the classification makes no upstream request. Presets SHALL be used only by the router's last fallback rung.

#### Scenario: A lookup goes light
- **WHEN** an ask in `dynamic` mode asks `What is the latest stable Python release?`
- **THEN** the routing is tier `light`, effort `low` or the nearest level the chosen model accepts, `selected_by` `router`, `classifier` `rules` and a non-empty `reason`

#### Scenario: A long analysis goes complex
- **WHEN** an ask in `dynamic` mode asks to compare two designs and evaluate their trade-offs
- **THEN** the routing tier is `complex` and the effort is at most `medium`

#### Scenario: The Decisions classifier supplies only the tier
- **WHEN** the Decisions classifier is configured and picks tier `complex`
- **THEN** the task class still comes from the rules and the call makes no upstream request beyond the one Decisions request

### Requirement: Dynamic tiers need no configuration
In `dynamic` mode the three tiers SHALL be effort tiers of the router and need no configuration. `PERPLEXITY_TIER_LIGHT`, `PERPLEXITY_TIER_STANDARD` and `PERPLEXITY_TIER_COMPLEX`, each optional and validated as a model id when set, SHALL pin that tier's calls to that model used verbatim: the router SHALL not choose the model, the effort SHALL still follow the tier (clipped to the pinned model's accepted levels when the matrix knows it), and no score SHALL be consulted. A pin applies to routed research too, and the attachment gate of `media-attachments` (`accepts` of the final route) applies to a pinned model as to any other: `no` is refused, `unknown` is sent. `PERPLEXITY_MODEL` SHALL be ignored in `dynamic` mode with one startup warning naming it, as in `custom` mode. Presets `high` and `xhigh` SHALL never be selected automatically for ask or chat, and `xhigh` never for research.

#### Scenario: Nothing configured
- **WHEN** the server starts in `dynamic` mode with only the API key set
- **THEN** it starts and the model of every nameless call is chosen by the router

#### Scenario: A tier replaced
- **WHEN** `PERPLEXITY_TIER_COMPLEX` is `anthropic/claude-opus-5-5` and a call classifies `complex`
- **THEN** the request names that model, the routing reason is `pinned` and the effort follows the tier

#### Scenario: A pin and a named tier
- **WHEN** `PERPLEXITY_TIER_COMPLEX` is set and an ask names `tier` `complex`
- **THEN** the pinned model runs, `selected_by` is `tier` and the reason says pinned

#### Scenario: A pin is gated like any model
- **WHEN** a tier is pinned to a model the matrix says refuses `image` and the call carries an image
- **THEN** the shared gate fails the call with `invalid_request` naming the model and `image`, and nothing is sent; for an `unknown` model the call is sent

#### Scenario: A pin on a model the matrix does not know
- **WHEN** a tier is pinned to a model the matrix has no entry for
- **THEN** the request names that model and sends no reasoning effort

#### Scenario: A pin leaves the other tiers routed
- **WHEN** only `PERPLEXITY_TIER_COMPLEX` is set and a call classifies `light`
- **THEN** the router chooses the model

#### Scenario: A bad tier variable
- **WHEN** `PERPLEXITY_TIER_LIGHT` holds a value that is not a plain model id
- **THEN** startup fails naming `PERPLEXITY_TIER_LIGHT`

#### Scenario: The model variable is ignored
- **WHEN** the server starts in `dynamic` mode with `PERPLEXITY_MODEL` set
- **THEN** it starts, ignores it and logs one warning naming the variable

### Requirement: A chat follow-up holds its tier
In `dynamic` mode a `perplexity_chat` send to an existing chat that names no selector SHALL route to the higher of the tier the dynamic classifier picks for the new message and the stored tier of the chat's previous assistant turn, never below it. It SHALL also keep the previous turn's model, recomputing only the effort from the held tier, when that turn's stored `routed_model` (the requested id of a router model route, not the API-reported `model`) is non-null, is an `available` key in the matrix and the matrix answers `yes` to the call's required kinds (for a chained send the new message's attachments together with the kinds inherited from earlier turns; for a replay the new message's attachments only, because a replay resends no earlier file); otherwise the router chooses afresh with those kinds. A named `depth`, `model` or `tier` is an explicit selector and SHALL resolve afresh with no hold. A `PERPLEXITY_TIER_*` pin of the held tier wins over a held model. The reason SHALL say when the tier or the model was held.

#### Scenario: Previous tier from the stored turn
- **WHEN** the previous assistant turn stored tier `complex`
- **THEN** a short follow-up routes at tier `complex`

#### Scenario: The model is held
- **WHEN** the previous turn's `routed_model` is `M`, available in the matrix, and the follow-up names nothing
- **THEN** the follow-up request names `M`, `selected_by` is `router` and the reason says the model was held

#### Scenario: Reported id differs from the requested id
- **WHEN** the previous turn requested `openai/gpt-6-luna` and the API reported `openai/gpt-5.6-luna` as its `model`
- **THEN** the hold uses `openai/gpt-6-luna`, the stored `routed_model`

#### Scenario: The held model was removed
- **WHEN** the previous turn's `routed_model` is `removed` in the matrix
- **THEN** the router chooses and the reason does not say held

#### Scenario: The held model is not a matrix key
- **WHEN** the previous turn's `routed_model` has no entry in the matrix
- **THEN** the router chooses

#### Scenario: A previous turn that was not a router model route
- **WHEN** the previous turn ran a preset, the fallback preset rung, an explicit `model` or a `standard` or `custom` mode route, so its `routed_model` is null
- **THEN** the router chooses the model

#### Scenario: The held model does not accept the required kinds
- **WHEN** a chained follow-up requires `image` (new, or inherited from an earlier turn's attachment) and the matrix does not answer `yes` for the held model
- **THEN** the router chooses afresh among models that do

#### Scenario: A replay inherits nothing
- **WHEN** a replay send carries no attachment and an earlier turn had an image
- **THEN** the required kinds are empty and the held model is kept if it is otherwise eligible

#### Scenario: A named tier resolves afresh
- **WHEN** a follow-up names `tier` `light`
- **THEN** the model is not held, the router (or a pin) chooses, and the stored tier of the new turn is `light`

### Requirement: A chat follow-up's previous tier is recovered from storage
The previous turn's tier SHALL be the tier stored with that assistant message (the tier the call ran at, a named tier included); for a message with no stored tier it SHALL be found by matching the stored preset to the documented preset of each tier (`fast` for `light`, `medium` for `complex`, and any other stored preset or model counting as `standard`).

#### Scenario: A turn with no stored tier
- **WHEN** the previous turn is an older row with preset `medium` and no stored tier
- **THEN** its tier counts as `complex`

#### Scenario: A model that matches no tier
- **WHEN** the previous turn ran an explicit model and stored no tier
- **THEN** its tier counts as `standard`

#### Scenario: A short follow-up to a complex chat
- **WHEN** a chat's first turn ran the `complex` tier and the next message is `and in 2025?`
- **THEN** the second turn runs at tier `complex` with `selected_by` `router` and a reason saying it was held at `complex`

#### Scenario: A longer question raises the tier
- **WHEN** a chat's first turn ran `light` and the next message classifies `complex`
- **THEN** the second turn runs at tier `complex`

#### Scenario: Explicit selectors still win
- **WHEN** a follow-up names `depth` `fast`
- **THEN** it runs preset `fast` with `selected_by` `depth`, whatever tier the chat last used

#### Scenario: Errors keep their order
- **WHEN** a nameless follow-up in `dynamic` mode names a chat that does not exist, or a send names an invalid selector
- **THEN** the call fails with `not_found` for the chat, and with `invalid_request` for the selector or any other invalid option before the chat is looked up, as in the other modes

### Requirement: Every ask and chat result reports its routing
`perplexity_ask` and `perplexity_chat` send SHALL return a `routing` object with `mode`, `tier` (null unless a tier applied), `model` (the id requested, or null for a preset), `effort` (the reasoning level sent, or null), `selected_by` (`default`, `tier`, `depth`, `model`, `router` or `fallback`), `classifier` (who supplied the tier when `selected_by` is `router` or `fallback`, `rules` unless another is configured; else null) and `reason` (short text, set when `dynamic` mode routed the call), so the caller sees what happened without being told the configuration.

#### Scenario: Custom default
- **WHEN** an ask names nothing in `custom` mode
- **THEN** the routing is mode `custom` (the mode) and tier `standard` (the `standard` tier, not the `standard` mode), model the `standard` tier's id, effort null, `selected_by` `default`

#### Scenario: Default call
- **WHEN** an ask names nothing in `standard` mode
- **THEN** the result's routing is mode `standard`, tier null, model `perplexity/sonar`, effort null, `selected_by` `default`

#### Scenario: Tier call
- **WHEN** an ask in `custom` mode names `tier` `light`
- **THEN** the routing is mode `custom`, tier `light`, the light model's id, effort null and `selected_by` `tier`

#### Scenario: Depth call
- **WHEN** an ask names `depth` `low`
- **THEN** the routing carries `selected_by` `depth`, model null and effort null

#### Scenario: Rules call
- **WHEN** an ask in `dynamic` mode names nothing and the router chooses a model
- **THEN** the routing is mode `dynamic`, a tier, that model, its effort or null, `selected_by` `router`, `classifier` `rules` and a non-empty `reason`

#### Scenario: Fallback call
- **WHEN** the router has no eligible model and runs `openai/gpt-6-luna`
- **THEN** the routing has `selected_by` `fallback`, that model, effort `low` or null when the model accepts none, and a reason naming the rung

### Requirement: Dynamic mode is told to the calling agent
The MCP `instructions` and the `perplexity_ask` and `perplexity_chat` description sentence SHALL, in `dynamic` mode, state the mode, that the server picks a model and a reasoning effort from the prompt when a call names nothing (using benchmark evidence and price), which tiers are pinned to a model by configuration, and that `tier`, `depth` or `model` overrides the choice. Both SHALL be pure functions of the settings, with no secret.

#### Scenario: Dynamic instructions
- **WHEN** a client initializes against a `dynamic` server
- **THEN** the instructions name mode `dynamic`, say the server picks a model and effort, name any pinned tier with its model, and say a named `tier`, `depth` or `model` overrides the server's choice

### Requirement: The tier argument
`perplexity_ask` and `perplexity_chat` send SHALL accept `tier`, one of `light`, `standard` and `complex`, valid only in `custom` and `dynamic` mode. In any other mode it SHALL fail with `invalid_request` naming `tier` and the active mode, and nothing is sent. A value outside the three SHALL fail with `invalid_request` naming `tier`. In `dynamic` mode a named `tier` SHALL skip the tier classifier (no Decisions request) but the offline rules SHALL still supply the task class, the router SHALL choose the model for that tier (or the pin SHALL), `selected_by` SHALL be `tier` and `classifier` null.

#### Scenario: Tier in custom mode
- **WHEN** an ask in `custom` mode names `tier` `complex`
- **THEN** the request names the `complex` tier's model

#### Scenario: Tier in dynamic mode
- **WHEN** an ask in `dynamic` mode names `tier` `light` with the Decisions classifier configured
- **THEN** no Decisions request is made, the rules supply the task class, the router chooses the model with the `light` effort, `selected_by` is `tier` and `classifier` is null

#### Scenario: Tier in standard mode
- **WHEN** an ask in `standard` mode names `tier` `light`
- **THEN** the call fails with `invalid_request` naming `tier` and the mode `standard`, and no request reaches the API

#### Scenario: Unknown tier
- **WHEN** an ask in `custom` mode names `tier` `huge`
- **THEN** the call fails with `invalid_request` naming `tier`

### Requirement: The classifier field can be decisions
Where `routing-config` says the `routing` object's `classifier` is the classifier that supplied the tier, its value SHALL be `decisions` or `rules` when the Decisions classifier is configured, as defined by "The classifier field says who supplied the tier" in `routing-decisions-classifier`, and null whenever the tier was not classified: `selected_by` `tier`, `depth`, `model` or `default`.

#### Scenario: Explicit selector
- **WHEN** a call in this mode names `tier`
- **THEN** the routing's `classifier` is null

#### Scenario: Router with the Decisions classifier
- **WHEN** a nameless call in this mode is routed after a confident Decisions answer
- **THEN** `selected_by` is `router` and `classifier` is `decisions`

### Requirement: Usage records the resolved model
The usage event of a routed call SHALL record the model the API reports, as it does today, and SHALL NOT change the usage schema. A call that ran a model route SHALL record and report preset null, a routed research run included: no code path SHALL fall back to a default preset name. Migration `0006` adds stored columns only (`chat_messages.tier`, `chat_messages.routed_model` and `research_jobs.effort`).

#### Scenario: Default call is recorded
- **WHEN** an ask in `standard` mode completes
- **THEN** one usage event exists whose model is the one the response reports

#### Scenario: A routed research run records no preset
- **WHEN** a routed research job is observed finished
- **THEN** its usage event has preset null and the model the response reports

### Requirement: The instructions text
The MCP `instructions` SHALL be rendered at startup from the settings and state the mode, the standard model or the three tiers with what each runs (a model id, or in `dynamic` mode `router` for a tier the server chooses a model for), when to pass `tier`, `depth` or `model`, that `high` and `xhigh` belong to `perplexity_research`, and that `perplexity_help` explains the tools. The text SHALL contain no secret and SHALL be identical for the life of the process. `perplexity_help` repeats the routing mode but is a pointer and a topic, not a fifth channel of "The calling agent is told the configuration".

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

### Requirement: Dynamic mode needs a model when search is off
**Reason**: every router route is a model route, so `search` false never conflicts with a preset any more; the one case left (the router's preset fallback rung, which is skipped when `search` is false) is covered by `routing-evidence`.
**Migration**: a call in `dynamic` mode with `search` false is routed like any other and sends no tools; a named `tier` with `search` false is accepted. Callers that relied on the `invalid_request` for a preset tier get the routed model instead.

### Requirement: Dynamic mode warns about a shadowed model variable
**Reason**: `PERPLEXITY_MODEL` means nothing in `dynamic` mode any more; "Dynamic tiers need no configuration" now states that it is ignored with one warning.
**Migration**: remove `PERPLEXITY_MODEL` from a `dynamic` configuration, or pin a tier with `PERPLEXITY_TIER_STANDARD`.

## ADDED Requirements

### Requirement: Router refusals come after option validation
In `dynamic` mode a call SHALL fail in this order: selector and tier errors, the attachment parse of `media-attachments`, any invalid option (checked against a provisional route that never raises a router error), a router refusal, the attachment gate on the final route, and only then may a Decisions request be made. If that request changes the route, the gate and the preset check SHALL run again on the final route.

#### Scenario: Invalid option beats a router refusal
- **WHEN** a nameless ask has both an invalid `recency` and an attached kind no model accepts
- **THEN** the call fails with `invalid_request` naming `recency`

#### Scenario: A reclassified tier whose pin refuses the kind
- **WHEN** the Decisions classifier reclassifies a call with an image to a tier whose `PERPLEXITY_TIER_*` pin the matrix says refuses `image`
- **THEN** the call fails with `invalid_request` and no request naming a model is sent

#### Scenario: Router refusal before the Decisions request
- **WHEN** the Decisions classifier is configured and the router would refuse the call
- **THEN** the call fails with the router's `invalid_request` and no Decisions request is made

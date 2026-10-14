# Proposal

## Why

Today every `perplexity_ask` and `perplexity_chat` call that names no depth silently runs the `fast` preset, and the only other choices are the preset names or an explicit model id that the calling agent must know. A person installing the server has no way to say "use this model", "use my own light, standard and complex models" or (later) "choose per prompt", and the calling agent has no way to learn which of those is in force: it sees only the tools. The ids behind a preset also move (`fast`, `low` and `medium` resolve to `openai/gpt-6-luna` as documented on 2026-10-06), so a default that names a preset is not stable, while the base `perplexity/sonar` model line is.

Probed live on 2026-10-13 through the running server: `perplexity/sonar` is in the live model catalog ($0.25 input and $2.50 output per 1M tokens), answers a time-sensitive question with web search and sources through the Agent API (one call: 4150 input tokens, $0.00379 reported, 3.6 s), and the model id `auto` is refused by the API (`model "auto" is not supported`). Sonar Reasoning Pro is no longer in the catalog.

## What Changes

- Add three routing modes, chosen by `PERPLEXITY_ROUTING`: `standard` (default), `custom` and `dynamic`. This change builds `standard` and `custom`; `dynamic` is a reserved value that fails startup with a message saying the classifier is not shipped yet (`routing-decisions-classifier` adds it), so the three-way choice is documented once and never changes shape.
- `standard`: one model, `PERPLEXITY_MODEL`, default `perplexity/sonar`. A call with no depth, tier or model uses it, grounded with the web search tool.
- `custom`: three tiers, `PERPLEXITY_TIER_LIGHT`, `PERPLEXITY_TIER_STANDARD` and `PERPLEXITY_TIER_COMPLEX`, all required in this mode (no hidden defaults). A call names a tier with a new `tier` argument; with none it uses the `standard` tier.
- The mode is a **default**, never a restriction: an explicit `model` on a call is used exactly as given in every mode (it is the override), and a call that names none falls back to the mode's default. `depth` (the Perplexity presets) stays available the same way. `tier` is refused outside `custom`.
- Tell the calling agent what is configured, through four channels that each work when another is ignored: the MCP server `instructions` rendered from the settings at startup, the `ask` and `chat` tool descriptions, a `routing` object in every ask and chat result (mode, tier, model, `selected_by`), and an active-routing section in `perplexity_models`.
- Show whether each configured model id is in the live catalog (`known` in `perplexity_models`) without making startup or any call depend on the network or on the answer.
- Document the three choices in the README setup: the recommended base-Sonar default and why, how dynamic will use Perplexity Decide to choose per prompt, and how to configure custom tiers.
- **BREAKING (inside 2.0.0, unreleased):** the default for a call with no depth changes from the `fast` preset to `perplexity/sonar` with web search.
- Out of scope: the `dynamic` classifier (`routing-decisions-classifier`), rules fallback (`routing-rules-v1`), escalation, measuring savings, `perplexity_research` (its presets are not models), any cost ceiling.

## Capabilities

### New Capabilities

- `routing-config`: the three modes and their settings, resolution of the model for a call, and how the active configuration is made known to the calling agent.

### Modified Capabilities

- `agent-ask`: "Ask tool" (description states the mode and default model), "Depth selects a preset" (the default no longer names `fast`) and "Explicit model" (conflicts owned by `routing-config`; `search` false now allowed on every model route).
- `agent-chat`: "Chat tool" (same description rule), "Send starts a chat" (the first-turn scenario no longer names preset `fast`) and "Send takes the ask options" (adds `tier`, tier per turn).
- `server-runtime`: "Configuration from environment" (five new variables, and `dynamic` refused) and a new requirement for the server instructions.
- `model-catalog`: a new requirement that `perplexity_models` reports the active routing.

`perplexity_chat` send shares the ask option path; `routing-config` states that it applies to both.

## Impact

- **Code:** `settings.py` (five settings, cross-field validation), a new `routing.py` (pure resolution), `agent.py` (`AskOptions` and `build_request` take the resolved route), `tools/ask.py` and `tools/chat.py` (`tier` argument, `routing` in the result, description text), `tools/models.py` (routing section), `server.py` (`instructions`), `README.md` and `CLAUDE.md`.
- **Tests (existing files edited):** `tests/test_settings.py`, `tests/test_ask_tool.py`, `tests/test_chat_send.py`, `tests/test_agent_request.py`, `tests/test_contract_checks.py`, `tests/test_catalog.py` and the models-tool tests.
- **Dependencies, migration, new tool:** none. The `tools/list` size grows by the `tier` argument and the `routing` result field (measured at apply, target under 3%).
- **Spend:** the default model costs more than the `fast` preset in the one probe (about $0.0038 against the $0.001 to $0.002 observed for `fast`); the design records this and the README says so. Live acceptance spends well under $0.05.
- **Privacy, tool surface:** unchanged (ten tools).

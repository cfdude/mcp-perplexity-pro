# Proposal

## Why

`PERPLEXITY_ROUTING=dynamic` is reserved and refused at startup, so nobody can have the server
pick a model per prompt, and the four epics behind this one (the Decisions classifier,
escalation, evaluation, the Router API) all need a first classifier to extend. A deterministic
rules classifier is the smallest slice that makes dynamic mode usable: it is offline, free,
testable against labeled prompts, and it stays as the fallback once a network classifier exists.

## What Changes

- New pure module of rules: `classify(text)` returns a tier (`light`, `standard`, `complex`), the
  ordered signals that fired and a short reason built from them, never from the prompt text. No network,
  no database, no cost, no usage event.
- `PERPLEXITY_ROUTING=dynamic` starts and works for `perplexity_ask` and `perplexity_chat` send:
  a call that names no `depth`, `tier` or `model` is classified and routed to a tier.
- Dynamic tiers need no configuration: light is the `fast` preset, standard is `PERPLEXITY_MODEL`
  (default `perplexity/sonar`), complex is the `medium` preset. `PERPLEXITY_TIER_LIGHT`,
  `PERPLEXITY_TIER_STANDARD` and `PERPLEXITY_TIER_COMPLEX` replace a default when set. Dynamic
  never selects `high` or `xhigh`, which stay behind `perplexity_research`.
- `tier` becomes valid in dynamic mode (it forces the tier and skips classification); an explicit
  `depth` or `model` is used as given, as in every mode.
- A chat follow-up never routes below the tier the chat last used; the tier is recovered from the
  stored preset or model of the previous turn, so there is no migration.
- A dynamic call with `search` false runs the standard tier's model (a preset always searches).
- The result's `routing` gains `reason` and a new `selected_by` value `rules`; the instructions
  text, the `perplexity_ask` and `perplexity_chat` description sentence, `perplexity_models` and
  the help routing topic describe dynamic mode.
- A labeled prompt set in the test suite is the contract for the rules. No cost or savings figure
  is claimed here; `routing-eval-tuning` owns that.

## Capabilities

### New Capabilities
- `routing-rules`: the offline rules classifier, its signals, its output and the labeled prompt set that pins it.

### Modified Capabilities
- `routing-config`: dynamic mode is accepted and resolves by rules (replaces "reserved"), `tier` is valid in dynamic, the resolution order, refusal order, shaping, default-route and instructions requirements and the `routing` result cover `rules`, presets and `reason`; dynamic tiers, the follow-up floor, search off, the shadowed-variable warning.
- `agent-ask`: "Depth selects a preset" no longer says a nameless call never runs a preset (it does in dynamic mode).
- `model-catalog`: the `perplexity_models` routing section reports dynamic mode, presets and the classifier.
- `help-tool`: the index routing line and the routing topic describe dynamic mode.

## Impact

- Code: new `src/mcp_perplexity_pro/rules.py`; `routing.py` (resolve, Route, description and
  instructions text), `settings.py` (dynamic accepted, tier variables optional there),
  `tools/ask.py` and `tools/chat.py` (pass the text; chat resolves after its read-only lookup),
  `storage/chats.py` (the last assistant turn's route), `tools/models.py`, `help_text.py`
  (index line and topic), the `tier` parameter descriptions; README, CHANGELOG, CLAUDE.md.
- Spec: the `routing-config` requirement "Dynamic mode is reserved" is removed.
- No migration, no new dependency, no new tool; the `tools/list` size must stay under the
  59779-byte budget (a `reason` field in two output schemas, a `preset` and `classifier` field in
  the models output, reworded `tier` descriptions), measured on a dynamic server too.
- No billed call is made by the classifier. Live acceptance makes a few small ask calls to see
  the routed models run.

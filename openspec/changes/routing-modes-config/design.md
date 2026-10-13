## Context

The consumer experience has three questions the code does not answer yet: which model runs when I say nothing, how do I pin my own models, and how does the *calling agent* (which sees only tools) know. Today `agent.AskOptions.preset` returns `depth or "fast"` and an explicit `model` is passed through unchecked (`agent.py:196-300`); `Settings` has no routing fields; `build_server` sets no MCP `instructions`; `perplexity_models` returns the live catalog plus a static documented preset table. Live probe, 2026-10-13: `perplexity/sonar` is in the live catalog, works through the Agent API with the web search tool, one call cost $0.00379 reported; `model: "auto"` is refused by the API (`validation failed: model "auto" is not supported`), so "auto" can only be something this server implements (that is `dynamic`, a later change).

## Goals / Non-Goals

**Goals:** a stable default (the base Sonar line), a three-tier custom setup, a reserved `dynamic` value so the choice is documented once, and four independent ways for the calling agent to learn the configuration. No migration, no new tool, no network at startup.

**Non-Goals:** the dynamic classifier, rules fallback, escalation, cost ceilings, tier use in `perplexity_research`, per-project routing, changing the model after startup (settings are fixed for the process, which is also what makes the instructions text static).

## Decisions

**D1. Settings.** `PERPLEXITY_ROUTING` (`standard`|`custom`|`dynamic`, default `standard`), `PERPLEXITY_MODEL` (default `perplexity/sonar`), `PERPLEXITY_TIER_LIGHT|STANDARD|COMPLEX`. A pydantic cross-field validator in `settings.py` collects every routing error into the existing multi-variable `SettingsError`. `dynamic` raises "not available in this version" (the classifier epic removes that one line and adds the classifier settings). In `standard`, set tier variables are ignored with one logged warning.

**D2. One pure function.** `routing.resolve(settings, *, depth, tier, model) -> Route(mode, tier, model, preset, source)`. It enforces pairwise conflicts (`depth`/`model`, `depth`/`tier`, `model`/`tier`), refuses `tier` outside `custom`, and never touches the network or the database. `agent.build_request` receives the `Route`: a `Route.preset` sends `preset`, a `Route.model` sends `model` with the web search tool and the step budget already used for an explicit model (so a default or tier call is shaped exactly like an explicit-model call, including the 4096-token default cap for `anthropic/` ids). Validation lives in `routing.py`; `agent.py` keeps request shaping. Both `perplexity_ask` and `perplexity_chat` send build their route through this one call (the call-site sweep names them).

**D3. The configuration is a default.** It supplies a model only when the call names none; an explicit `model` is always used verbatim (spec "The mode is a default, never a restriction"). **No selector combines; the default applies when none is given.** `model`, `depth` and `tier` are pairwise exclusive (the spec's "Resolution order" is the one owner of those conflicts); a single explicit selector beats the configured mode, and the mode default applies when there is none. An operator who wants a hard lock has none: there is no cost ceiling in this server by design (CLAUDE.md non-goals), and an agent that passes `model` explicitly is making a choice the operator's own agent made. Recorded as a risk below.

**D4. Telling the agent: four channels, ordered by how sure we are they arrive.** (1) Every ask and chat result carries `routing` (always delivered, in-band). (2) The `perplexity_ask` and `perplexity_chat` descriptions get one rendered sentence (every client lists tools). (3) `perplexity_models` gains a `routing` section (an agent that asks "what can I use" gets it, with the `known` flag). (4) FastMCP `instructions` (pure function of settings: `routing.instructions_text(settings)`), which some clients show and some drop, hence the other three. Descriptions are built at registration from the settings, so `register_tools(server, settings)` and each `register(server, settings)` gain a `settings` argument (today they take only `server`, and tools read settings at call time through `ctx.lifespan_context`); `build_server` passes it. The description text is part of the pinned-schema tests. The description states the mode and default model but not the cost (bytes); the README carries the Sonar cost. Alternative rejected: a `perplexity_config` tool (an eleventh tool costs about 4 to 6 KB in every session; the other channels already cover it).

**D5. `tier` is one argument, always in the schema.** Conditional schemas (the argument present only in `custom`) would save a few bytes but make the contract depend on startup state and complicate the pinned-schema tests; the description says "custom mode only". Cost: a short argument on two tools, measured at apply (target under 3% of `tools/list`).

**D6. Catalog check is reporting, not gating.** `perplexity_models` marks each configured id `known` true, false, or null (catalog unreadable). Startup does not read the catalog (startup order is settings, data dir, client, listen), no call waits on it, and an unlisted id is still sent: the catalog can lag a new model and a typo is reported by the API on the first call as it is today.

**D7. Default cost honesty.** The default changes from the `fast` preset to `perplexity/sonar` with web search. In the probe the Sonar call cost $0.00379 (4150 input tokens: the web search tool's retrieved pages count as input) against $0.001 to $0.002 observed for `fast`: one data point, roughly twice. The user chose a stable model line over the cheapest option (presets move; `fast` resolved to `openai/gpt-6-luna` on 2026-10-06). The README (not the tool description) states the figure and the one-line way back to the old behaviour: `depth: "fast"` on a call, or `PERPLEXITY_MODEL` set to any id. This change does not claim a saving.

**D8. No usage-schema change.** The event's `model` is already what the API reports. Recording the tier would help the later eval epic; it is deferred to `routing-eval-tuning` (it would need a column and a migration), named in the routing notes.

**D8a. The preset fallback is removed, not bypassed.** `agent.DEFAULT_DEPTH` and the `options.depth or DEFAULT_DEPTH` fallback in `AskOptions.preset` and `build_request` go; `Route.preset` is the only source of a preset, so a chat message stored for a Sonar call records preset null and `ChatResult.depth` is null (main `agent-chat` "Send is recorded" already stores the requested preset, null for an explicit model).

**D8b. Model switching in a chat is probed, not assumed.** A chained chat send passes `previous_response_id`; changing the model between turns (tier per turn) was never probed. The acceptance task runs it once; if the API refuses it, the tool refuses a model change on a chained send with `invalid_request` pointing to `replay` (a follow-up amendment before archive).

**D9. Research unchanged.** `perplexity_research` depths (`medium`, `high`, `xhigh`) are presets with their own multi-minute semantics and a model that is only known when the run completes (`agent.snapshot_model`), so routing does not apply; the README says so.

## Risks / Trade-offs

- **An agent can bypass the operator's tiers with `model` or `depth`.** Accepted (D3); the `routing.source` field makes every bypass visible in the result and in the instructions text ("override only when the user asks"). A lock setting is a later change if wanted.
- **Default is dearer than `fast` in one measurement** (D7). Mitigation: stated in README and tool description; `perplexity_usage` shows the real cost.
- **A tier model with the wrong capabilities** (a model without web search support) fails at the API on first use with its error; not pre-validated because the catalog does not list capabilities (the catalog payload carries id and pricing only, observed in the probe).
- **Instructions are static per process**, so a settings change needs a restart (the supervised process restarts anyway).
- **`dynamic` documented before it exists.** Mitigated by refusing it at startup with a clear message, never silently falling back to `standard`.
- **Tool schema growth** (D5): measured at apply and recorded in `CLAUDE.md` with the earlier measurements.

## Migration Plan

No database change. Behaviour change for existing 2.0.0 development installs: a no-depth ask now uses `perplexity/sonar`. The pm2 environment needs no edit (defaults apply); `ecosystem.example.cjs` gains the optional routing variables, commented.

## Open Questions

None blocking. Whether a lock setting (`PERPLEXITY_ROUTING_LOCK`) is wanted is deferred until someone asks.

## Observed shapes (evidence)

- `perplexity_models` (provider `perplexity`, 2026-10-13): live ids include `perplexity/sonar` ($0.25 in, $2.50 out, $0.0625 cache read per 1M); no Sonar Reasoning Pro.
- `perplexity_ask` with `model: perplexity/sonar`: completed, 15 sources, answer correct for the probe question, `usage` 4150 in / 104 out, `cost_usd` 0.00379, `cost_source` reported, 3568 ms.
- `perplexity_ask` with `model: auto`: `[invalid_request] validation failed: model "auto" is not supported`.

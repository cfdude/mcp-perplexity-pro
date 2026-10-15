# Design

## Context

`routing.resolve()` already owns the three selectors and the mode defaults (see
`openspec/specs/routing-config/spec.md`); `dynamic` parses but `settings.py` refuses it at
startup. A `Route` is a model or a preset. The chat tables store `model` and `preset` of each
assistant turn, so the tier a chat last used can be recovered without a migration. The default
Sonar ask costs about $0.0034 and `fast` about $0.0012 (one sample each, README), so the rules
choose between small amounts; the point is sending hard questions to a stronger run and never
reaching `high` or `xhigh`. See proposal.md for the motivation.

## Goals / Non-Goals

**Goals:**
- Make `PERPLEXITY_ROUTING=dynamic` work with zero extra configuration.
- Keep the classifier pure so the Decisions classifier (`routing-decisions-classifier`) can call it
  as a fallback and escalation can reuse its tiers.
- Make the rules testable against a labeled prompt set, with no invented accuracy number.

**Non-Goals:**
- No network classifier, no escalation, no cost ceiling, no savings claim (the later epics).
- No change to `perplexity_research` or to explicit selectors.
- No new column or migration for the chat tier.

## Decisions

**D1. `rules.py` is a pure module with one entry, `classify(text) -> Classification`.**
`Classification` is a frozen dataclass: `tier`, `confidence`, `reason`, and `signals` (a tuple of
signal names, for tests and the later eval). No settings, no I/O. Alternative: put it in
`routing.py`; rejected because `routing.py` is about selectors and text, and the classifier will
grow (and gain a sibling that calls the network).

**D2. Signals and initial thresholds.** Complex: two or more distinct hits from a fixed analysis
vocabulary (about 20 phrases: compare, evaluate, trade-offs, pros and cons, step by step, root
cause, architecture, in depth, design, derive, prove, analyze, critique, ...), or 1200 characters
or more, or three or more questions (question marks) or numbered list items. Light: at most 120
characters, one question, a lookup opening (what is, who is, when did, where is, how many, how
much, define, latest, current, price of), no complexity signal. Standard: the rest. Confidence is
`high` when two complexity signals hold, or a light lookup matched, or a rule ruled out the other
tiers; `low` otherwise. The numbers are starting points that the labeled set pins and
`routing-eval-tuning` tunes; they are not claims about accuracy. Alternatives: a trained
classifier (needs data and a dependency, and is what the Decisions epic is for), prompt-length
alone (misroutes short hard questions).

**D3. The reason is built from signal names only.** `classify` assembles it from constants
(`"2 analysis terms"`, `"1500 chars"`, `"3 questions"`, `"short lookup"`), never from the text,
so it can be returned and logged without leaking a prompt. A test classifies a prompt holding a
secret-shaped string and checks the reason.

**D4. Tiers resolve to a `Route` through one table.** `routing.dynamic_route(settings, tier)`
returns `Route(mode="dynamic", tier, model, preset, selected_by)`: light is preset `fast`, standard
is `settings.tier_standard or settings.model`, complex is preset `medium`; each `PERPLEXITY_TIER_*`
that is set replaces its default with a model id (so `preset` is null there, as for any model
route). `high` and `xhigh` are not in the table, so dynamic cannot select them by construction.
Alternative: require the three tier variables as `custom` does; rejected because dynamic must work
with nothing set, and `custom` already covers the all-explicit case.

**D5. `resolve()` gains two optional arguments, `text` and `previous`.** In dynamic mode with no
selector it classifies `text` (`previous` is the tier of the chat's last turn or None) and returns
`selected_by="rules"` with `reason`. With a selector the behavior is exactly today's (a test
asserts classify is not called). `Route` gains `reason: str | None = None`. Refusal order is
unchanged; `tier` is accepted when the mode is `custom` or `dynamic`.

**D6. The follow-up floor needs no migration.** `perplexity_chat` send reads the last assistant
message's `(preset, model)` and `routing.tier_of(settings, preset, model)` maps it to a tier by
comparing with `dynamic_route` of each tier; no match is `standard`. The floor is the max of that
and the classified tier. Alternative: a `tier` column on `chats`; rejected because it needs a
migration for information the stored rows already imply, and the sticky behavior only matters in
dynamic mode.

**D7. Settings.** `dynamic` leaves the refusal list. `_check_routing` accepts it; `tier_*` stay
optional (validated as model ids when set); `ignored_routing_vars()` reports none for dynamic.
The startup log names the mode and the three tiers' routes once, at INFO.

**D8. Surfaces.** `Routing` (result model, shared by ask and chat) gains an optional `reason`;
`selected_by`'s description adds `rules`. `routing.instructions_text` and `description_sentence`
render a dynamic variant; `tools/models.py` routing section adds `classifier` and per-tier entries
(a preset or a model with `known`); `help_text` routing topic gets a dynamic variant. The
`tools/list` budget test (59779 bytes) must still pass; the additions are two field descriptions
and one enum word, measured in the acceptance step.

## Risks / Trade-offs

- [Lexical rules misread a prompt] → the wrong tier costs a little or answers with a lighter
  model; mitigation: explicit selectors always win, `reason` shows why, the labeled set pins the
  behavior, and the Decisions classifier and escalation epics add second opinions.
- [Routing to `fast` loses quality for a lookup that was harder than it looked] → the light
  verdict needs a lookup opening, one question and 120 characters or fewer; anything ambiguous is
  `standard`, never `light`.
- [`medium` costs more than Sonar for a complex prompt] → intended: that is what complex means;
  `high` and `xhigh` stay unreachable, so the worst case is the documented `medium` range.
- [A follow-up floor keeps a chat on `complex` after the topic gets easy] → bounded and cheap
  relative to a wrong drop; the caller can pass `depth`, `tier` or `model` for a turn.
- [The initial vocabulary is a guess] → no accuracy or savings number is stated anywhere; the eval
  epic owns that.

## Migration Plan

No data change. Default behavior is unchanged: `standard` stays the default and `dynamic` is
opt-in. Rollback is unsetting `PERPLEXITY_ROUTING`.

# Design

## Context

`routing.resolve()` already owns the three selectors and the mode defaults (see
`openspec/specs/routing-config/spec.md`); `dynamic` parses but `settings.py` refuses it at
startup. A `Route` is a model or a preset. The chat tables store `model` and `preset` of each
assistant turn, so the tier a chat last used can be recovered without a migration. The default
Sonar ask costs about $0.0034 and `fast` about $0.0012 (one sample each, README), and `medium` about $0.016 to
$0.025 (five to seven times Sonar, README), so the rules choose between small amounts at the cheap
end and a real step up at `complex`; the point is sending hard questions to a stronger run and never
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
`Classification` is a frozen dataclass: `tier`, `reason`, and `signals` (an ordered tuple of
signal names, built in a fixed order so two processes agree under hash randomization). There is no
confidence value: nothing uses one yet, and the Decisions epic can add it when it needs it. No settings, no I/O. Alternative: put it in
`routing.py`; rejected because `routing.py` is about selectors and text, and the classifier will
grow (and gain a sibling that calls the network).

**D2. Signals, matching and initial thresholds.** Text is trimmed and case-folded; length is
`len()` of the trimmed text. Complex when any holds: (a) two or more distinct entries of the
analysis vocabulary match as whole words: compare, comparison, evaluate, evaluation, trade-off,
trade-offs, tradeoff, tradeoffs, pros and cons, step by step, root cause, architecture, in depth,
analyze, analyse, analysis, critique, derive, prove, design, implications (the list is a module
constant pinned by its test); (b) length is 1200 or more; (c) three or more questions, where a
question is a `?`, `？` or `؟` followed by whitespace or the end of the text (so a URL query string
is not one), or three or more lines that start with a number and `.` or `)`. Light when none of
those fired, length is 120 or less, at most one question, and the text opens with a lookup form
(regex over: what is, what are, who is, who was, when did, when is, where is, how many, how much,
define, latest, current, price of). A text with no question mark can still be a lookup (`define
idempotent`). Standard otherwise. The numbers and lists are starting points that the labeled set
pins and `routing-eval-tuning` tunes; they are not claims about accuracy. Alternatives: a trained
classifier (needs data and a dependency; that is the Decisions epic), length alone (misroutes short
hard questions).

**D3. The reason is built from signal names only.** `classify` assembles it from constants
(`"2 analysis terms"`, `"1500 chars"`, `"3 questions"`, `"short lookup"`, and `"search off"` or `"held at complex"` where the follow-up floor or `search` false applied), never from the text,
so it can be returned and logged without leaking a prompt. A test classifies a prompt holding a
secret-shaped string and checks the reason.

**D4. Tiers resolve to a `Route` through one table.** `routing.dynamic_route(settings, tier)`
returns `Route(mode="dynamic", tier, model, preset, selected_by)`: light is preset `fast`, standard
is `settings.tier_standard or settings.model`, complex is preset `medium`; each `PERPLEXITY_TIER_*`
that is set replaces its default with a model id (so `preset` is null there, as for any model
route). `high` and `xhigh` are not in the table, so dynamic cannot select them by construction.
Alternative: require the three tier variables as `custom` does; rejected because dynamic must work
with nothing set, and `custom` already covers the all-explicit case.

**D5. `resolve()` gains optional `text`, `previous` and `search`.** In dynamic mode with no
selector it classifies `text`, applies the floor from `previous` (a tier name or None) and
returns `selected_by="rules"` with `reason`; with `search` false it returns the standard tier's
route without classifying; with `text=None` (a caller that has none, such as a test) it returns the
standard tier with `selected_by="default"`. With a selector the behavior is today's (a test asserts
the classifier is not called). `Route` gains `reason: str | None = None`. `_default_description`
and the conflict message learn the dynamic wording ("with neither, the tier is picked from the
prompt"). `tier` is accepted when the mode is `custom` or `dynamic`; the refusal order is
unchanged and its message drops "custom only". A filtered preset route is allowed, as it is with an
explicit `depth` (the page-fetch loss is already documented on `perplexity_ask`); only `search`
false needs the model route, because `agent.build_request` refuses it with a preset.

**D6. The follow-up floor needs no migration, and chat resolves after its lookup.** A new
`storage.chats.last_route(session, chat_id) -> (preset, model) | None` reads the last assistant
message's stored `preset` and `model`. `routing.tier_of(settings, preset, model)` checks the preset
first (the stored preset column holds the preset name for a preset run), then the stored model
against each tier's configured model; a tie takes the highest tier, no match is `standard`.
In `perplexity_chat` a send that names a selector resolves exactly as today, before any database
access, so invalid selectors still beat `not_found`; only a nameless send to an existing chat in
dynamic mode defers `resolve` into `_send`, after the read-only chat lookup that already
produces `not_found`, so the order of errors is preserved. A new chat has no previous turn. The
stored `model` is the model the API reports; acceptance compares the reported id with the requested
one for `perplexity/sonar` and an `anthropic/` id on a live call, and if they differ the match
falls back to standard (documented, never an error). Alternative: a `tier` column on `chats`;
rejected because it needs a migration for what the stored rows already imply.

**D7. Settings.** `dynamic` leaves the refusal list. `_check_routing` accepts it; `tier_*` stay
optional (validated as model ids when set) and `PERPLEXITY_MODEL` is validated as in standard mode;
`ignored_routing_vars()` reports `PERPLEXITY_MODEL` only when `PERPLEXITY_TIER_STANDARD` is also
set, and nothing else. `__main__` logs the mode and the three tiers' routes once at INFO (a test
checks the line holds no secret).

**D8. Surfaces.** `Routing` (shared by ask and chat) gains an optional `reason`; its
`selected_by` description adds `rules` (it is a plain string, not an enum). `routing.instructions_text`
and `description_sentence` render a dynamic variant; the `tier` parameter descriptions in
`tools/ask.py` and `tools/chat.py` say "custom or dynamic mode"; `tools/models.py` gives
`ConfiguredModel` an optional `preset` (and a nullable `id`) and `RoutingSection` an optional
`classifier`; `help_text._routing_line` and the `routing` topic get a dynamic variant (index stays
within 1500 bytes). `tests/test_tools_list_budget.py` measures a default server, so acceptance also
measures a dynamic one and records both numbers.

## Risks / Trade-offs

- [Lexical rules misread a prompt] → the wrong tier costs a little or answers with a lighter
  model; mitigation: explicit selectors always win, `reason` shows why, the labeled set pins the
  behavior, and the Decisions classifier and escalation epics add second opinions.
- [Routing to `fast` loses quality for a lookup that was harder than it looked] → the light
  verdict needs a lookup opening, one question and 120 characters or fewer; anything ambiguous is
  `standard`, never `light`.
- [`medium` costs more than Sonar for a complex prompt] → intended: that is what complex means;
  `high` and `xhigh` stay unreachable, so the worst case is the documented `medium` range.
- [A long paste with a trivial question reaches `medium`: the 1200-character signal is length alone] → accepted for v1 and visible in `reason`; the eval epic tunes it, and the caller can name `depth` or `model`.
- [A synchronous `medium` run can last 39 to about 90 s against the 120 s `PERPLEXITY_AGENT_READ_TIMEOUT`, so a slow one could be billed but unreadable] → the same exposure an explicit `depth` `medium` has today; accepted, and acceptance records the observed time; escalation or a longer timeout is a later decision.
- [A follow-up floor keeps a chat on `complex` after the topic gets easy] → bounded and cheap
  relative to a wrong drop; the caller can pass `depth`, `tier` or `model` for a turn.
- [The initial vocabulary is a guess] → no accuracy or savings number is stated anywhere; the eval
  epic owns that.

## Migration Plan

No data change. Default behavior is unchanged: `standard` stays the default and `dynamic` is
opt-in. Rollback is unsetting `PERPLEXITY_ROUTING`.

# Proposal

## Why

The rules classifier of `routing-rules-v1` reads a prompt's length, vocabulary and shape; it cannot
tell that a short question is hard. Perplexity's Decisions API classifies text with a small model
for about $0.02 per million input tokens, which is the "classification model" Rob's dynamic mode
was designed around. This change lets dynamic mode ask it for the tier, with the rules as the
always-available fallback.

## What Changes

- New setting `PERPLEXITY_CLASSIFIER` (`rules` default, `decisions`), used only in dynamic mode.
- With `decisions`, a nameless call in dynamic mode asks the Decisions API one `choice` question
  (tier: light, standard or complex) over the prompt, within a hard 3-second limit that covers any
  retries, and routes to the tier it picks. When its confidence is under 0.5 the higher of its
  tier and the rules' tier wins.
- Any failure (timeout, rate limit, upstream error, unreadable or unknown answer) falls back to the
  rules, says so in the routing `reason`, and never fails the call.
- Each Decisions request is one recorded usage event (api `decisions`, the calling tool's name,
  the call's project), so its cost is visible in `perplexity_usage`.
- It runs only when the call names no selector and `search` is not false, and only after the
  call's options validated, so an invalid call spends nothing.
- The routing `classifier` field (added by `routing-rules-v1`) can now be `decisions`; the instructions text, the
  models routing section and the help routing topic name the classifier in use.
- No savings or accuracy claim: live acceptance records how the two classifiers compare on the
  labeled prompt set as a measurement, and `routing-eval-tuning` owns any claim.

## Capabilities

### New Capabilities
- `routing-decisions-classifier`: the Decisions-API tier classification, its confidence rule, bound, fallback, recording and when it runs.

### Modified Capabilities
- `routing-config`: the `PERPLEXITY_CLASSIFIER` setting, the `decisions` value of the routing `classifier` field, the instructions text naming the classifier.
- `cli`: a costed command records one event per upstream request (two for an ask with this classifier).
- `server-runtime`: the configuration variable.
- `usage-recording`: a nested request is recorded under the calling tool.
- `model-catalog`: the `perplexity_models` routing section names the Decisions classifier.
- `help-tool`: the routing topic names the classifier and its fallback.

## Impact

- Code: new `src/mcp_perplexity_pro/routing_decisions.py`; `decisions.run_decide` takes the
  calling tool's name; `settings.py` (the setting and its warning); `routing.py` (`Route`
  gains `classifier`, texts); `rules.py` unchanged; `tools/ask.py` and `tools/chat.py` (classify
  after validation, before the final route); `tools/models.py`; `help_text.py`; README, CHANGELOG,
  CLAUDE.md.
- Depends on `routing-rules-v1` (its rules, `Route.reason`, dynamic mode and the follow-up floor).
  It is applied after that change is archived; `routing-rules-v1` words its shared requirements
  classifier-neutral so these deltas compose by ADDED requirements, plus one MODIFIED (`cli`).
- No migration, no new dependency, no new tool; `tools/list` stays under the 59779-byte budget.
- Cost: one Decisions request per nameless dynamic call, billed on input tokens at the documented
  20 nano-USD each. A 4000-character prompt is roughly 1000 tokens (an estimate, not a measurement),
  so about two thousandths of a cent; live acceptance records the real figure. Latency adds up to
  3 seconds in the worst case.

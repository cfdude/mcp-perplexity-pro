# Proposal

## Why

The 2026-10-29 review of Perplexity's changes (`acceptance/drift-review.md`, verified live) found
four places where the server is behind the API: the Agent API renamed the request field `preset` to
`effort` (the old name is a deprecated alias that may disappear), the documented effort levels moved
(`high` now runs `openai/gpt-6.1-terra`, not `gpt-6-sol`), the Decisions API gained models
(`pplx-decider-v1.2`, the half-price `pplx-decider-flash-v1.2`, and `latest` aliases) that our tool
refuses, and the pricing page grew a table that breaks the test that guards our price constants.
All four are small; leaving them is what turns into a silent break when the alias is removed.

## What Changes

- Every Agent API request the server builds (ask, chat send, research submit) names its preset in
  the body field `effort` and no longer sends `preset`; the preset names and our tools' `depth`
  arguments are unchanged, and a response whose `effort` and `preset` carry versioned values
  (`fast@2026-10-16.0`) is read as before (a real response is captured as a fixture).
- The documented preset table in `perplexity_models` and the README follows the documentation as of
  2026-10-29 (`high` runs `openai/gpt-6.1-terra`).
- `perplexity_decide` accepts `pplx-decider-v1.2`, `pplx-decider-flash-v1.2`, `pplx-decider-latest`,
  `pplx-decider-flash-latest` and `perplexity/pplx-decider-latest`, besides the two names it takes
  today (the default stays `pplx-decider-v1.1-27b`), and prices each at its documented rate
  (flash $0.01, the others $0.02 per million input tokens).
- The pricing page test reads only the first table under a heading and the Decisions table of the
  new models; the recorded excerpt is re-recorded and the price constants are re-dated.
- Out of scope, recorded: the decider default and the classifier's model (they need an evaluation:
  on one example flash and v1.2 answered differently from v1.1), images for the Decisions API,
  `ultra-preview` as a research depth, documents and images as Agent inputs (`media-inputs`).

## Capabilities

### New Capabilities
- none.

### Modified Capabilities
- `agent-ask`: Agent requests carry the preset as `effort`; versioned response values are read as before.
- `model-catalog`: the documented preset table is as of 2026-10-29.
- `decisions-tool`: the accepted models and their prices.

## Impact

- Code: `agent.py` (two request builders), `catalog.py` (`PRESETS`), `decisions.py`, `pricing.py`,
  `tools/decisions.py` (the model parameter text), `help_text.py`, `redaction.py` (comment and
  exemption check); tests: request-equality tests that compare with recorded requests (they map
  `preset` to `effort`), `tests/pricing_page.py`, the pricing fixture excerpt; README, CHANGELOG, CLAUDE.md.
- No migration: the stored `preset` columns keep the preset names we request.
- Live verification (needs Agent API credit, now available): ask, chat and research submit with the
  `effort` body; decide with each model.

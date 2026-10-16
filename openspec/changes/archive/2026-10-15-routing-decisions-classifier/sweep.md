# Call-site sweep (task 4.1)

Derived with `rg` on 2026-10-15 at `a60d59b`.

## Callers of `run_decide(` (`rg "run_decide\(" src`)
- `tools/decisions.py:93` (the `perplexity_decide` tool): unchanged, `tool` defaults to `perplexity_decide`.
- `routing_decisions.py:139`: the classifier, passing `tool=` (the calling tool) and `deadline=`.
No other caller; `run_decide` stays the one `costed_call` caller for the Decisions API.

## The one-sequence rule (CLAUDE.md "Production callers")
- `record_usage(` call sites: `costed.py:95`, `costed.py:114`, and the observation core in
  `agent.py`; unchanged. `costed_call(` callers: `agent.py`, `search.py`, `decisions.py`,
  `embeddings.py`; unchanged (the classifier reaches it through `run_decide`). Holds: no third
  site and no fifth caller.

## Where the classifier runs (`rg "classify_dynamic|wants_decider" src`)
- `tools/ask.py:224,250`: gate by `wants_decider(...)`, validate the project name and options first
  with a provisional route, then classify. Holds.
- `tools/chat.py:239,242`: for a follow-up, `settings.classifier == "decisions" and floor !=
  "complex"` inline, after `last_route`. This repeats part of `wants_decider`'s condition by hand
  rather than calling it; the other conditions (nameless, dynamic, `search` not false) are decided
  earlier in `perplexity_chat`. Noted for Gate 2 (sibling-site rule).
- `tools/research.py`, `tools/jobs.py`, `tools/search.py`, `tools/embeddings.py`: no routing,
  unchanged by every mode. Justified omissions.

## Readers of the new setting (`rg "\.classifier\b" src`)
- `settings.py` (validation in dynamic mode only, ignored list), `routing.py` (instructions and
  description sentences), `help_text.py` (index and topic), `tools/models.py` (section and text),
  `routing_decisions.py`: every surface that names the mode names the classifier. Holds.

## Prompt text (privacy)
- The prompt reaches only the Decisions request body; the reason is built from constants
  (`routing_decisions.py`), checked by a secret-shaped-string test over the reason, the log
  records and the stored usage event. Holds.

## Inverses
- Decisions classifier on: `PERPLEXITY_CLASSIFIER=decisions` in dynamic mode; off: unset it (default
  `rules`); tested both ways.
- A Decisions answer is overridden by any explicit selector (no request is made), by `search` false,
  and raised to the follow-up floor.
- Recording has its inverse in failure: a failed or timed-out request is recorded with its
  category (the timeout sits inside the recorded call).

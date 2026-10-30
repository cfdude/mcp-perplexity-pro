## 0. Before apply

- [ ] 0.1 Record Gate 1 (`record-gate-review api-drift-2026-10 --gate 1 --verdict pass --base-sha <a> --head-sha <b> --reviewer ... --artifact <each of proposal.md, design.md, tasks.md and the three spec.md files>`; pm#252) after a fresh-context review of the artifacts; add the change to a release (`release release-2-3-0 --member api-drift-2026-10`, target 2.3.0, intent unpublished like 2.1.0 and 2.2.0) and, because the release holds several spec files, record a fresh-context cross-spec review (`record-cross-spec-review release-2-3-0`); ORDER: before group 1 and again after any amendment

## 1. Effort instead of preset

- [ ] 1.1 RED then GREEN: capture a real response `tests/fixtures/agent_fast_effort.json` (one `fast` ask, about $0.001, with `.meta.json`; through `tests/test_live_capture.py`, restoring any tracked fixture the capture overwrites); `agent.build_request` and the research submit send `effort` and no `preset`; update every test that compares a recorded request body; new tests for each scenario of the `agent-ask` delta (ask, chat send, research submit; the versioned response digests, stores and records preset `fast`, a chat follow-up recovers its tier) and a test that no digest code reads `effort` or `preset` from a response (`rg` the source); mutation-checks: send `preset` again, record the response's value instead of the request's, each turns a test red

## 2. The preset table

- [ ] 2.1 RED then GREEN: `catalog.PRESETS` to the documentation of 2026-10-29 (D2), README preset table and the `perplexity_models` help entry, the tests that pin the table; the `model-catalog` delta scenario; mutation-check: revert `high` to `gpt-6-sol` and watch the test go red

## 3. Decisions models and prices

- [ ] 3.1 RED then GREEN: `decisions.MODELS` and the `tools/decisions.py` model text, `pricing.DECISIONS_NANO_PER_INPUT_TOKEN` as the complete table with `decisions_cost_nano(model, input_tokens)`, `decisions_usage` passing the model, the unknown-model rule (D3), `PRICES_AS_OF` left for 4.1; tests for every scenario of the `decisions-tool` delta (each of the five new names carried verbatim; flash 347 tokens gives 3470 nano-USD; an unlisted name is `invalid_request` before any call; every accepted name stored verbatim by the recorder, none redacted); the classifier and its tests stay on the default; mutation-checks: price flash at 20, drop a name from the table (cost becomes unknown, not 20), each turns a test red

## 4. The pricing guard

- [ ] 4.1 RED then GREEN: `tests/pricing_page.py` reads every table under a heading (D4), re-record `tests/fixtures/pricing_page.json` and its `.meta.json` from the live page, extend `tests/test_pricing_live.py` to pin the Decisions rows for the five new names against `pricing.py`, then move `PRICES_AS_OF` to 2026-10-29 once the live test passes; a unit test that the parser survives an extra table and still fails when a needed price row is missing

## 5. Acceptance (live)

- [ ] 5.1 Live on a scratch instance (ephemeral port, temporary data directory, real key from the environment, never the live pm2 app): (a) ask at `fast` and `medium`, a chat send and a follow-up, a research submit at `medium` then its result, all through the `effort` body; (b) decide with `pplx-decider-v1.2`, `pplx-decider-flash-v1.2` and `pplx-decider-latest`, the recorded cost against the reported token counts; (c) `uv run pytest -m live` for `tests/test_agent_live.py`, `tests/test_client_live.py` and `tests/test_pricing_live.py` (diff and restore any fixture a live capture overwrites); (d) `perplexity_usage` reconciles the events to the nano-USD; save the outputs under `openspec/changes/api-drift-2026-10/acceptance/`; expected spend under $0.15

## 6. Gate procedure (required, per the pm conductor)

- [ ] 6.1 Call-site completeness sweep: for every rule this change introduces (requests carry `effort` and never `preset`, the table follows the documentation, every accepted decider name has a price and a recorder pass-through, an unknown name is never priced) enumerate all call sites mechanically with `rg` (every `"preset"` request key and `PRESETS` reader, every `DECISIONS_NANO_PER_INPUT_TOKEN` and `decisions_cost_nano` caller, every `MODELS` user, README and help mentions of presets and decider names) and state where each rule holds and where not; include the inverse (a request field that is removed upstream, a decider name that Perplexity retires: the 400 passes through as an upstream error)
- [ ] 6.2 Verify against each task's commit, not the working tree: for every task above run `git show --stat <sha>` and assert each file the task claims to change appears in that commit
- [ ] 6.3 Attribute every commit of this change to its epic with `update-epic api-drift-2026-10 --attribute-commit <sha>` as each lands, in landing order; never attribute the archive move or the pm bookkeeping commits; verify the last attributed commit is the Gate 2 head
- [ ] 6.4 Route what the work taught: practices, tooling friction and process lessons, each named as one of those three kinds; write `openspec/changes/api-drift-2026-10/routing.md` with exactly three lines `practice: ...`, `tooling: ...` and `process: ...`, each naming the filed item or reading `none, because <reason that names the command or commit checked>`
- [ ] 6.5 Gate 2 implementation review by a fresh-context reviewer over the full committed range, fix Critical and Important findings, then `record-gate-review api-drift-2026-10 --gate 2 --verdict pass --base-sha <a> --head-sha <b>`; verify the verdict reaches the last attributed commit

## 7. Documentation (after Gate 2 is clean)

- [ ] 7.1 README (request field note, preset table, decider models and the flash price in the Decisions section, every dollar figure that `help_text.py` shows), `CLAUDE.md` (rows and counts that changed; keep the pm block byte-identical), `CHANGELOG.md` under Unreleased, a check that every example matches the acceptance output
- [ ] 7.2 Record Gate 2 again over the docs range after a fresh-context check of the documentation diff; verify the recorded head equals the last attributed commit before the archive task runs
- [ ] 7.3 Archive the change (`/opsx:archive api-drift-2026-10`), then the epic disposition with `update-epic api-drift-2026-10 --status archived --outcome delivered --reason "<what shipped>" --no-deferrals` <!-- pm:lifecycle -->

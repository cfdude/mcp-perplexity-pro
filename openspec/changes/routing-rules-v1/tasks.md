## 0. Before apply

- [ ] 0.1 Record Gate 1 (`record-gate-review routing-rules-v1 --gate 1 --verdict pass --base-sha <a> --head-sha <b> --reviewer ... --artifact openspec/changes/routing-rules-v1`) after a fresh-context review of the artifacts; create release `release-2-1-0` (`release release-2-1-0 --member routing-rules-v1`; 2.0.0 already shipped) and run a fresh-context cross-spec review of the four spec deltas against the main specs (`record-cross-spec-review release-2-1-0`); ORDER: before group 1 and again after any amendment

## 1. The classifier

- [ ] 1.1 RED then GREEN: the labeled set `tests/fixtures/routing_prompts.json` (at least 40 prompts, at least 10 per tier, each with `expected` and `mark` clear or borderline, written before the rules) and `tests/test_rules_labeled.py`; then `src/mcp_perplexity_pro/rules.py` with pure `classify` (D1 to D3); tests `tests/test_rules.py` for each scenario of the `routing-rules` spec (determinism, reason holds no prompt text, two analysis words, long text, three questions, lookup, short non-lookup, ordinary question, non-Latin text); `rg` proves `rules.py` imports no settings, httpx, sqlalchemy or fastmcp (a test blocks those imports); mutation-checks: raise the length threshold above every long prompt and delete one vocabulary class, each turns a test red

## 2. Settings and routes

- [ ] 2.1 RED then GREEN: `settings.py` accepts `dynamic` (remove the refusal, keep the unknown-value message listing three modes, `tier_*` optional and validated when set, `ignored_routing_vars` empty for dynamic); `routing.py` gains `Route.reason`, `dynamic_route`, `tier_of`, and `resolve(..., text=, previous=)` per D4 to D5; tests in `tests/test_settings.py` and `tests/test_routing.py` for each scenario of the `routing-config` delta (dynamic starts with nothing set, tier variable replaces a default, bad tier variable names the variable, `tier` accepted in dynamic and refused in standard, explicit selectors never classify (classify patched to raise), `high` and `xhigh` unreachable by enumerating every tier and signal, refusal order unchanged); update the tests that assert dynamic is refused (found with `rg "dynamic" tests/`)

## 3. Tools

- [ ] 3.1 RED then GREEN: `tools/ask.py` and `tools/chat.py` pass the query or message (and, for a chat send to an existing chat, the previous turn's `tier_of`) to `resolve`, the `Routing` model gains `reason` and `rules`; tests through `build_server` with a `MockTransport` for each scenario of the delta: lookup goes `fast`, analysis goes `medium`, a replaced tier runs its model, follow-up floor (short follow-up to complex stays complex, longer raises, explicit depth wins), the request body of a preset route equals a `depth` request, usage records the resolved model or preset and exactly one event, no upstream request for the classification; mutation-check: remove the follow-up floor and confirm red

## 4. Telling the agent

- [ ] 4.1 RED then GREEN: `routing.instructions_text` and `description_sentence` render dynamic (D8), `tools/models.py` routing section reports `classifier` and the three tiers (preset or model with `known`), `help_text` routing topic dynamic variant (at most 3000 bytes, every dollar figure still in the README); tests: instructions, description sentence, `perplexity_models` section against the live-shaped fixture, help topic, and `tests/test_tools_list_budget.py` still passes (measure `tools/list` and record the byte count in `acceptance/README.md`)

## 5. Acceptance (live)

- [ ] 5.1 Restart pm2 from the ecosystem file with `PERPLEXITY_ROUTING=dynamic` set (`pm2 restart ecosystem.config.cjs --update-env`, then one authenticated call before counting it verified; docs/lessons/restart-pm2-from-the-ecosystem-file.md) on a scratch instance, not the live one, started with a temp data directory; run four ask calls (a lookup, an ordinary question, a long comparison, one with an explicit `model`) and one two-turn chat; confirm each result's routing, the models run and the ledger matches the nano-USD; save outputs under `openspec/changes/routing-rules-v1/acceptance/`; cost cap about one cent per call, well under the approved limit

## 6. Gate procedure (required, per the pm conductor)

- [ ] 6.1 Call-site completeness sweep: for every rule this change introduces (dynamic accepted, rules classify only when nothing is named, the follow-up floor, high and xhigh unreachable, tier accepted in dynamic, `Route.reason`) enumerate all call sites mechanically with `rg` (every `resolve(` call, every `Route(` construction, every place that reads `settings.routing`, every place `selected_by` is matched or documented, README and help text mentions of dynamic being reserved) and state where each rule holds and where not; include the inverses (a classifier verdict an explicit selector overrides; a floor a caller can leave by naming a selector; dynamic mode unset by unsetting the variable)
- [ ] 6.2 Verify against each task's commit, not the working tree: for every task above run `git show --stat <sha>` and assert each file the task claims to change appears in that commit
- [ ] 6.3 Attribute every commit of this change to its epic with `update-epic routing-rules-v1 --attribute-commit <sha>` as each lands, in landing order; never attribute the archive move, the pm bookkeeping commits or an ancestor after a later commit; verify the last attributed commit is the Gate 2 head
- [ ] 6.4 Route what the work taught: practices, tooling friction and process lessons, each named as one of those three kinds; write `openspec/changes/routing-rules-v1/routing.md` with exactly three lines `practice: ...`, `tooling: ...` and `process: ...`, each naming the filed item or reading `none, because <reason that names the command or commit checked>`
- [ ] 6.5 Gate 2 implementation review by a fresh-context reviewer over the full committed range, fix Critical and Important findings, then `record-gate-review routing-rules-v1 --gate 2 --verdict pass --base-sha <a> --head-sha <b>`; verify the verdict reaches the last attributed commit

## 7. Documentation (after Gate 2 is clean)

- [ ] 7.1 README: "Choosing how models are picked" gains the dynamic mode (what it does, the three default tiers, the overrides, the follow-up floor, that no savings are claimed), the `PERPLEXITY_ROUTING` row no longer says reserved, the `dynamic` row in the mode table, the `ecosystem.example.cjs` comment; `CLAUDE.md` (module table gains `rules.py`, routing row, the non-goal list loses "the dynamic routing mode" and keeps the Decisions classifier, the tools/list size) keeping the pm block byte-identical; `CHANGELOG.md` entry; verify every example against the acceptance output
- [ ] 7.2 Record Gate 2 again over the docs range after a fresh-context check of the documentation diff; verify the recorded head equals the last attributed commit before the archive task runs

## 8. Archive

- [ ] 8.1 Archive the change and record the disposition (`update-epic routing-rules-v1 --status archived --outcome delivered --no-deferrals`, or name each deferral); verify `openspec list` no longer shows it and `PROJECT.md` renders it archived <!-- pm:lifecycle -->

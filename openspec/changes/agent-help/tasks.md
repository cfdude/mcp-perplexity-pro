## 0. Before apply

- [ ] 0.1 Record Gate 1 (`record-gate-review agent-help --gate 1 --verdict pass --base-sha <a> --head-sha <b> --reviewer ... --artifact openspec/changes/agent-help`) after a fresh-context review of the artifacts, and add `agent-help` to `release-2-0-0` (`release release-2-0-0 --member agent-help`) with a fresh-context cross-spec review of `help-tool` and the `server-runtime` delta against the main specs and the other release specs (`record-cross-spec-review release-2-0-0`); ORDER: before group 1 and again after any amendment

## 1. Help text

- [ ] 1.1 RED then GREEN: `src/mcp_perplexity_pro/help_text.py` with pure `render_index`, `render_tool`, `render_topic`, `TOPICS` and the curated entries for all ten existing tools plus help itself, importing neither FastMCP nor storage (a test imports the module with those names blocked); tests `tests/test_help_text.py`: index at most 1500 bytes naming every tool once and the five topics and the routing mode; each topic at most 3000 bytes; every curated entry's example validates against the tool's input schema (jsonschema) and every result key it names exists in the output schema; every dollar figure appears in `README.md`; the `costs` topic names its samples; a registered tool without an entry fails; mutation-check: delete one tool's entry and confirm the coverage test goes red

## 2. The tool

- [ ] 2.1 RED then GREEN: `tools/help.py` with `perplexity_help` (actions `index`, `tool`, `topic`; `tool` reads the arguments and result keys from the registered tool's schemas at call time; unknown or missing `name` refused with `invalid_request` listing valid names; read-only annotations; no usage, no project), registered in `tools/__init__.py`; tests `tests/test_help_tool.py` through `build_server`: each action, an argument added to a stub tool appears in its help, refusals, zero usage events and zero projects, annotations and output schema; update the tool-name lists in `tests/test_server.py` and `tests/test_contract_checks.py` to eleven

## 3. Errors point to help

- [ ] 3.1 RED then GREEN: `ErrorContractMiddleware` appends the help sentence to an `invalid_request` from any tool except `perplexity_help` (both a `PerplexityError` and a framework `ValidationError`), never to other categories; tests in `tests/test_tool_errors.py` (or the file that owns the middleware tests) for each scenario of the `server-runtime` delta, including that the category and structured fields are unchanged; update any test that asserts an exact `invalid_request` message; mutation-check: remove the append and confirm red

## 4. Trim the descriptions

- [ ] 4.1 Trim the prose in the descriptions of `perplexity_chat`, `perplexity_jobs`, `perplexity_ask`, `perplexity_research` and `perplexity_embed` to the statements their specs require plus a closing pointer to `perplexity_help` (the removed text lives in the help topics); keep `tests/test_ask_tool.py`, `tests/test_chat_send.py` and the other description-pinning tests green; measure `tools/list` with one POST and `wc -c` against 59779 and record the number (and any shortfall) in `acceptance/README.md`

## 5. Acceptance (live)

- [ ] 5.1 Restart pm2 from the ecosystem file (`pm2 restart ecosystem.config.cjs --update-env`, never by name with `--update-env`: docs/lessons/restart-pm2-from-the-ecosystem-file.md) and make one authenticated call before counting the restart as verified; call `perplexity_help` for the index, one tool and one topic, and one deliberately invalid `perplexity_ask` call to read the hint; verify `tools/list` lists eleven tools and its byte size; confirm `perplexity_usage` shows no new event from the help calls; save the outputs under `openspec/changes/agent-help/acceptance/`; no spend

## 6. Gate procedure (required, per the pm conductor)

- [ ] 6.1 Call-site completeness sweep: for every rule this change introduces (every registered tool has help, the hint on every `invalid_request`, the five descriptions pointing to help, the size cap) enumerate all call sites mechanically with `rg` (every `register(` in `tools/`, every place `ErrorContractMiddleware` builds an error, every `invalid_request` raise site that bypasses the middleware, every description that mentions costs or a default) and state where each rule holds and where not, with the justification; include the inverses (a help entry that exists must fail the suite when its tool is removed; a hint that is appended is never appended to help's own errors)
- [ ] 6.2 Verify against each task's commit, not the working tree: for every task above run `git show --stat <sha>` and assert each file the task claims to change appears in that commit
- [ ] 6.3 Attribute every commit of this change to its epic with `update-epic agent-help --attribute-commit <sha>` as each lands, in landing order; never attribute the archive move, the pm bookkeeping commits or an ancestor after a later commit; verify the last attributed commit is the Gate 2 head
- [ ] 6.4 Route what the work taught: practices, tooling friction and process lessons, each named as one of those three kinds; write `openspec/changes/agent-help/routing.md` with exactly three lines `practice: ...`, `tooling: ...` and `process: ...`, each naming the filed item or reading `none, because <reason that names the command or commit checked>`
- [ ] 6.5 Gate 2 implementation review by a fresh-context reviewer over the full committed range, fix Critical and Important findings, then `record-gate-review agent-help --gate 2 --verdict pass --base-sha <a> --head-sha <b>`; verify the verdict reaches the last attributed commit

## 7. Documentation (after Gate 2 is clean)

- [ ] 7.1 README: a "Getting help" section (the `perplexity_help` actions with an example call and an excerpt of the index, the error hint, that the same text will back the CLI's `--help`), the tool table gains `perplexity_help`, tool counts become eleven; `CLAUDE.md` (module table gains `help_text.py` and `tools/help.py`, the tool-count note with the re-measured `tools/list` size, the current-change pointer) keeping the pm-managed block byte-identical; `CHANGELOG.md` entry under `2.0.0`; verify every example against the acceptance output
- [ ] 7.2 Record Gate 2 again over the docs range after a fresh-context check of the documentation diff; verify the recorded head equals the last attributed commit before the archive task runs

## 8. Archive

- [ ] 8.1 Archive the change and record the disposition (`update-epic agent-help --status archived --outcome delivered --no-deferrals`, or name each deferral); verify `openspec list` no longer shows it and `PROJECT.md` renders it archived <!-- pm:lifecycle -->

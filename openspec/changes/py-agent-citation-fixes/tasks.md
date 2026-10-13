## 1. Sources keep every id

- [x] 1.1 RED then GREEN: `agent.Source` gains `ids` (default `[]`) and `_sources` collects every distinct integer id per URL in first-seen order with `id` as the first (a boolean or non-integer id is ignored); tests against `tests/fixtures/agent_background_cancelled.json` (`rs-stats` ids `[10, 71]`) and `agent_background_completed.json` (ids 1, 11 and 21 each reachable), fetch-only (`ids` empty) and the repeated-URL case; mutation-check: restore the early `continue` once and confirm the new tests go red
- [x] 1.2 RED then GREEN: a stored job whose `sources_json` holds only `id` still returns through `perplexity_jobs` result with `ids` empty (extend `tests/test_chat_actions.py:152-160`, `tests/test_job_observation.py:84` and `tests/test_agent_digest.py:54-70`); the text rendering of sources in `tools/ask.py:72-78` and `tools/jobs.py:275-279` shows `(ids 10, 71)` and is unchanged for a source without ids; verify chat has no text render of sources

## 2. Structured answers

- [x] 2.1 RED then GREEN: a marker cleaner in `agent.py` applied by `digest` to the parsed `answer_json` (string leaves only, recursive, trailing runs only, the count in a warning, the raw answer unchanged) implemented as a scan from the end of each string with an iterative walk and a total fallback (no regex search), with every scenario of the spec including the linear-time scenario (500000 spaces and 500000 repeated markers, a time bound), the 100-level depth limit (a result that serialises, null with a warning past it), the bounded ids per URL (64, linear time), a cleaner failure part-way leaving the value uncleaned, `[2024]`, `[0]` and `a[1,2]` kept, a value that is only markers, keys untouched and the exact warning text; mutation-check by removing the cleaner call once and by swapping in a backtracking regex once (the time test must go red)

## 3. Documentation of measurements

- [x] 3.1 Correct `README.md` (the marker numbering paragraph, the medium row of the cost table, the `fast` confidence note), the ask, chat and research tool descriptions (`tools/ask.py`, `tools/chat.py`, `tools/research.py`: the medium range and the markers sentence) and add the correction note to the archived `py-agent-api` design only as a dated errata line; verify with `rg -n "not numbered like" README.md src` returning nothing (the main spec's 'unverified' wording is replaced by the delta at archive)

## 4. Acceptance (live)

- [x] 4.1 Measure `tools/list` before and after (the combined growth with `routing-modes-config` is measured once both are applied) (`wc -c` of one POST, as in CLAUDE.md; `Source` is shared by ask, chat, research and jobs) and record it in `CLAUDE.md`'s tool-size note at 6.1; restart pm2 (approved by Rob, standing) and, on the throwaway project `acceptance-citations` (expected under $0.10): one medium `perplexity_research` on a multi-entity question, then check every `[web:N]` in its answer appears in some source's `ids` and record the count; one `perplexity_ask` with a `json_schema` of string fields that invites citations, recording whether markers came back and whether `answer_json` is clean; reconcile `perplexity_usage` for the project to the nano-USD; delete the project; save the outputs under `openspec/changes/py-agent-citation-fixes/acceptance/` and record the measured time and cost of the medium run

## 5. Gate procedure (required, per the pm conductor)

- [x] 5.1 Call-site completeness sweep: for every rule this change introduces (every cited id reachable in `sources`, `id` equals the first of `ids`, marker removal only in `answer_json` string leaves, raw answer unchanged, stored rows tolerated) enumerate all call sites mechanically with `rg` (every producer and consumer of `Source`, `_sources`, `sources_json` and `answer_json`: ask, chat send, research submit and observation, jobs result, the stored-row reader) and state where each rule holds and where not, with justification; name the inverse (an `ids` list that can be written must be readable from old rows)
- [x] 5.2 Verify against each task's commit, not the working tree: for every task above run `git show --stat <sha>` and assert each file the task claims to change appears in that commit
- [x] 5.3 Attribute every commit of this change to its epic with `update-epic py-agent-citation-fixes --attribute-commit <sha>` as each lands, in landing order, ending with the last commit; never attribute the archive move, pm bookkeeping commits or an ancestor after a later commit; verify the last attributed commit is the Gate 2 head
- [x] 5.4 Add `py-agent-citation-fixes` to `release-2-0-0` (`release release-2-0-0 --member py-agent-citation-fixes`) and review this change's one delta spec (`agent-ask`) against the main `agent-chat`, `agent-research` and `local-storage` specs and the other release specs with a fresh-context reviewer; fix BLOCKS and record `record-cross-spec-review release-2-0-0`
- [x] 5.5 Route what the work taught: write `openspec/changes/py-agent-citation-fixes/routing.md` with exactly three lines `practice: ...`, `tooling: ...` and `process: ...` each naming the filed item or `none, because <reason naming the command or commit checked>`; the process line names the lesson that a doc claim resting on two samples of one query must say so
- [x] 5.6 Gate 2 implementation review by a fresh-context reviewer over the full committed range, fix Critical and Important findings, then `record-gate-review py-agent-citation-fixes --gate 2 --verdict pass --base-sha <a> --head-sha <b>`; verify the verdict reaches the last attributed commit

## 6. Documentation (after Gate 2 is clean)

- [x] 6.1 `CLAUDE.md` (the `agent.py` module row mentions `ids` and the marker cleaner; the current-change pointer) keeping the pm-managed block byte-identical; `CHANGELOG.md` entry under `2.0.0`; record Gate 2 again over the docs range after a fresh-context check of the documentation diff

## 7. Archive

- [ ] 7.1 Archive the change and record the disposition (`update-epic py-agent-citation-fixes --status archived --outcome delivered --no-deferrals`); verify `openspec list` no longer shows it and `PROJECT.md` renders it archived <!-- pm:lifecycle -->

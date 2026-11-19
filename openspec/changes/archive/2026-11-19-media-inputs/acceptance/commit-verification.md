# Verification against each task's commit (task 6.2)

Method (2026-11-19): for every ticked task, the commit that landed it was found with
`git log --all --grep "task N.N"` (per-task commits live on `epic/routing-v2-media-inputs`, still
reachable; the PR #49 range `f579378^1..f579378^2` carries the squashed media-only equivalents
2f0574d, 00b3ca9, a6ae5fb, 3065ad4, 662d6f4, 368daf8 plus the fix commits). For each, `git show
--name-only <sha>` was compared with the files the task text says it changes (a scripted basename
match of every backticked file in the task, then each non-match read by hand). A path the task only
READS or names as a pattern is not a claim. Result: every claimed file is in its commit; no task fails.

| Task | Commit | Claimed files in THAT commit | Notes |
|---|---|---|---|
| 0.1 | 0ee7b0e | yes: `.conductor/state.json` (Gate 1, cross-spec, Gate 2 records), `render-stamp.json`, `PROJECT.md`, `tasks.md` tick | bookkeeping |
| 0.2 | 370754f (tick only) | n/a: task says no-op; `pyproject.toml:61` `extend-exclude` already holds `openspec/**/acceptance/scripts` (added by 662d6f4 on this branch, pre-existing on the epic branch), verified by `rg -n extend-exclude pyproject.toml` | conditional task, satisfied as no-op |
| 0.3 | bbe2c4f | yes: `tasks.md` (the review mode itself is state, recorded in 0ee7b0e) | |
| 0.4 | 4a2f36e | yes: `acceptance/split-plan.md` | |
| 0.5 | 5e8f4f0 | yes: `tasks.md` (precondition satisfied, no files claimed) | |
| 1.1 | f2b2a8e | yes: `tests/media_support.py`, `tests/test_live_capture.py`, `tests/fixtures/*.json` + `.meta.json`, `acceptance/probe.md` | `design.md` is a source it reads, not changed |
| 1.2 | 9fe26e9 | yes: `media.py`, `redaction.py`, `server.py`, `usage.py`, `tests/test_media.py`, `tests/test_media_scrub.py` | |
| 1.3 | fecadd4 | yes: `media_read.py`, `media.py`, `settings.py`, `__main__.py`, `README.md`, `tests/test_media_read.py` | `ecosystem*.cjs` is a deny-list pattern, not a file |
| 1.4 | 7c089f6 | yes: `agent.py`, `tests/test_agent_media_request.py` | |
| 1.5 | 7b2b98a | yes: `tools/ask.py`, `call_flow.py`, `media.py`, `media_read.py`, `server.py`, `__main__.py`, `tests/test_ask_attachments.py` | |
| 2.1 | e63067e | yes: `matrix.py`, `data/model_matrix_baseline.json`, `acceptance/scripts/baseline_inputs.py`, `tests/test_matrix_inputs.py` | `acceptance/sweep.json` and `grok-4-7-investigation.md` are INPUTS (added earlier by e681249 and 62f6517), not changes |
| 2.2 | 6b76fcc | yes: `matrix_refresh.py`, `matrix.py`, `client.py`, `probe_media.py`, tests | |
| 2.3 | e32d430 | yes: `media_gate.py`, `call_flow.py`, `agent.py`, `tools/ask.py`, `tools/chat.py`, `tests/test_ask_gate.py`, `tests/test_call_flow.py` | |
| 2.4 | e996817 | yes: `tools/models.py`, `tests/test_models_inputs.py`, `tests/test_models_efforts.py` (the 16000-byte assertion) | `tests/test_tools_list_budget.py` is named as left alone until 3.3 |
| 3.1 | a799e7c | yes: `tools/chat.py`, `media_notes.py`, `storage/chats.py`, `call_flow.py`, `media_gate.py`, `tests/test_chat_attachments.py`, `tests/test_media_notes.py` | |
| 3.2 | af2a313 | yes: `tests/test_media_schema.py` | |
| 3.3 | 8dfeb4a | yes: `tests/test_tools_list_budget.py`, `acceptance/tools-list-budget.md` | |
| 4.1 | 597cd45 | yes: `command.py`, `tests/test_command_parser.py`, `tests/test_command_run.py` | |
| 4.2 | d740fd1 | yes: `help_text.py`, `tools/help.py`, `tests/test_help_tool.py`, `tests/test_media_help.py` | |
| 5.1 | 368daf8 | yes: `acceptance/live-5-1.md`, `acceptance/scripts/live_5_1.py`, captures | |
| 6.5 | 0ee7b0e | yes: `.conductor/state.json` carries the Gate 2 record | |
| 6a.1 | 8adfb52, e968266, 3e8232b, d658e6e, 51c4c5f, c10b0c4, 352ba1b, 6fedb3c, 0243be8, 72f3b68, 7e03e76 | yes per fix: `media_read.py` (C1, C2, C8), `tools/chat.py` (C3), `matrix.py`/`media_gate.py`/`matrix_refresh.py` (C4), `matrix_refresh.py` (C5), `agent.py`/`call_flow.py`/`tools/*.py` (C6, C7), `storage/embeddings.py` + `media_notes.py` (C10), `command.py` (C11), `redaction.py`/`usage.py`/`log_setup.py` | |
| 6a.2 | 9d50376, 7f41827, f2b1667, 6668366 | yes: `design.md`, `proposal.md`, the seven `specs/*/spec.md` across the four commits | |
| 7.1 | 77b2340 | yes: `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `docs/lessons/a-cancel-cleanup-finally-must-not-await-before-releasing.md` | `sweep.json`, `tools-list-budget.md`, `help_text.py`, `media.py` are read for figures, not edited |
| 7.2 | e434253 (docs fixes), 0ee7b0e (Gate 2 re-record) | yes: `README.md`, `CLAUDE.md`; `state.json` | |
| 7.3 | dadad2d | yes: change directory moved under `archive/2026-11-19-media-inputs/`, `openspec/specs/*` synced | |

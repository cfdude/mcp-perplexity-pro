# Tools-list budget (media-inputs task 3.3)

Measured 2026-11-19 on the three test servers (the method of `tests/test_tools_list_budget.py`:
the raw `tools/list` HTTP response, dummy key, temporary data directory), at three commits of
branch `epic/routing-v2-media-inputs`, each exported with `git archive` and measured in isolation.

| Variant | Starting commit | Now | Growth | Cap | Left |
|---|---|---|---|---|---|
| default | 57735 | 58245 | +510 | 59779 | 1534 |
| dynamic | 58021 | 58531 | +510 | 59779 | 1248 |
| dynamic with Decisions | 58255 | 58765 | +510 | 59779 | 1014 |

Starting commit: `main` at `8dfa8e4`, which measures the same as `7c089f6` (task 1.4, the last
commit before any schema change of this change): the router-owned commits already on the branch
change no listed byte.

Gross growth by tool (identical in the three variants): `perplexity_ask` +203, `perplexity_chat`
+209 (`attachments` with its 86- and 92-character description), `perplexity_models` +85 (the
`inputs` string, description "Inputs taken; empty: unknown", limit 120), `perplexity_help` +13 (the
sixth topic named in its description). Total 510, against the cap of 900 (design D14).

`perplexity_search` and `perplexity_decide` are byte-identical to the starting commit
(sha256 prefixes `1e4aab4731f90f3e` and `a3a6370d4b8378c4`, pinned in the test).

## Re-measure after the review fixes (2026-11-19)

Measured again at branch head `6fedb3c` (after review fixes C1 to C12 and S5, same method, three test
servers): default 58245, dynamic 58531, dynamic with Decisions 58765. Identical to the table above:
the fixes changed no listed byte. Growth over the starting commit stays 510 (cap 59779, growth cap 900).

## Re-measure on this branch (2026-11-19, round 2)

Measured on branch `epic/media-inputs` (cut from `main`, routing-v2 held) at head `0243be8`, same
method: default 58245, dynamic 58531, dynamic with Decisions 58765 (growth +510 over 57735, 58021,
58255; cap 59779). The earlier table above was taken from the held branch; this one is the shipped one.

## Waiver of the 300-byte trim

Task 3.3 waives its trim only when `routing-v2` is unmerged after its evaluation failed and the
measure against the base commit fits: the gross growth of 510 is at most 900 against the standalone
headroom of 2044, 1758 and 1524 bytes (left: 1534, 1248, 1014). Owner decision 2026-11-19:
`media-inputs` is released on its own and `routing-v2` is on hold (its coverage gate failed). No
trim was made.

## Ceilings in force

This change sets its own, never above 59779: default 58250, dynamic 58550, dynamic with Decisions
58800 (`CEILING` in `tests/test_tools_list_budget.py`), plus the growth cap of 900 over the
starting figures. `routing-v2` task 6.4, when it resumes, sets the final ceilings from this table
and has to raise these for its own growth.

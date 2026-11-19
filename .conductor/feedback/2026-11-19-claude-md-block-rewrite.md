Title: update-epic / record-gate-review rewrite the managed block of CLAUDE.md on every write verb, leaving an unrelated working-tree change to revert before each commit

What happened: in a repo whose committed CLAUDE.md holds the pm managed block, a write verb (`update-epic <id> --attribute-commit <sha>`, and the same with `record-gate-review`) prints "refreshed rules block in CLAUDE.md (platform: claude-code)" and leaves CLAUDE.md modified (measured 2026-11-19, pm 0.56.0: `git diff --stat CLAUDE.md` = 48 insertions, 72 deletions after one `--attribute-commit`). A verb that changes nothing ("already attributed ... Nothing was written") leaves CLAUDE.md alone, so the rewrite comes with real writes only.

Why it matters: the rewrite is unrelated to the change being recorded, so it lands in the next `git add -A` or has to be reverted by hand (`git checkout -- CLAUDE.md`) before every commit. About 15 times across one change (media-inputs), each a chance to commit an unreviewed 120-line rewrite of the project's instruction file, or to forget and leave the tree dirty.

Not diagnosed: whether the committed block simply lags the 0.56.0 template (then `/pm:upgrade` would commit it once and the churn stops) or the render is not stable. If it is lag, the verb should say so ("block is stale, run /pm:upgrade") instead of silently rewriting on every call.

Wanted: write the rules block only on `/pm:init` and `/pm:upgrade`, or when the block is missing; otherwise report drift in one line and leave the file alone.

Repro: pm 0.56.0, a repo with a committed block older than the installed engine, `update-epic <id> --attribute-commit <sha>`, then `git status`.

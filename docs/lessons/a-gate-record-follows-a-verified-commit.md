---
name: a-gate-record-follows-a-verified-commit
kind: process-failure
trigger: Chaining `openspec validate && git commit ; update-epic --attribute-commit $(git rev-parse HEAD) ; record-gate-review --head-sha $(git rev-parse HEAD)` in one shell command after editing specs.
cost: In pypi-publish `openspec validate --strict` exited non-zero on a length warning, the `&&` skipped the commit, and the `;` that followed still ran, so Gate 1 was recorded against the previous commit while the amended specs sat uncommitted. It was caught by reading the log, re-committed, and Gate 1 and the cross-spec verdict were recorded again. The same shape had already skipped a commit once in py-cli.
enforced_in: the commit step prints `git log --oneline -1` and `git status --short` before any record verb in these runs, and this lesson; the record verbs read `HEAD` only after a commit is confirmed.
---

Run the validation as its own command and look at its result before the commit; run the commit,
confirm it landed (`git log -1`, clean `git status`), and only then run `update-epic
--attribute-commit` and `record-gate-review` with the commit's hash. Never put a `;` between a
`&&` chain and a verb that records the state of `HEAD`.

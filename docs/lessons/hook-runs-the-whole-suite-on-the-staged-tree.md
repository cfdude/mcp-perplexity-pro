---
name: hook-runs-the-whole-suite-on-the-staged-tree
kind: process-failure
trigger: Splitting one working-tree change into several per-task commits by staging only part of it.
cost: In py-search-api, three attempted per-task commits for tasks 1.1 to 1.3 each failed the pre-commit hook (16 failures, then 1) because pre-commit stashes the unstaged files and runs the whole suite against the partial tree, and a later task's tests need an earlier-written but unstaged file. Cost about five minutes of hook runs and left the work as one combined commit.
enforced_in: .pre-commit-config.yaml (`uv run --locked pytest` over the staged tree). Commit tasks in dependency order, writing each task's code and tests together, or combine tasks that cannot be green alone and say so in the commit message.
---

Write and commit one task at a time (code and its tests), so every commit is green by itself.
When several tasks were already written together, commit them as one and name all task numbers.

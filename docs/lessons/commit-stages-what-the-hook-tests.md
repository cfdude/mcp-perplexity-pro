---
name: commit-stages-what-the-hook-tests
kind: process-failure
trigger: Committing a change that adds a dependency or any file outside the usual source, test and docs paths, using a staging helper with a fixed path list.
cost: In py-embeddings the `numpy` commit (01fd08e) staged `src`, `tests` and the change directory but not `pyproject.toml` or `uv.lock`. The pre-commit hook ran green because it tests the working tree, so a clean checkout of that commit would have failed to import numpy. Caught by reading `git show --stat`, fixed by commit 58e0585.
enforced_in: the commit helper stages `pyproject.toml` and `uv.lock` (task 11.2 of every change: `git show --stat <sha>` must list every file the task claims, and CI's `uv sync --locked` fails a manifest that does not match the lock).
---

After any commit that touches dependencies, run `git show --stat HEAD` and look for the manifest
and the lock file. A staging helper with a fixed path list must be extended when a change adds a
kind of file it did not know about.

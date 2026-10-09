---
name: uv-frozen-does-not-check-the-lock
kind: process-failure
trigger: Writing a CI install step or a hook that runs `uv sync` or `uv run`.
cost: The planned CI step used `uv sync --frozen`, which trusts the lockfile and never compares it to pyproject.toml, so the "lockfile out of date" scenario could not have failed. Found only in spec review. A hook running plain `uv run` can also re-lock silently.
enforced_in: .github/workflows/ci.yml (`uv sync --locked`), .pre-commit-config.yaml (`uv run --locked pytest`), quality-gates spec "Reproducible dependencies".
---

`--locked` asserts the lock is current and fails if not; `--frozen` only avoids updating it.
Use `--locked` wherever the lockfile is meant to be a gate.

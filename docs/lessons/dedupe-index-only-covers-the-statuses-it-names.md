---
name: dedupe-index-only-covers-the-statuses-it-names
kind: process-failure
trigger: Relying on a partial unique index (here `(api, request_id)` where status = 'ok') to make a "record once" step idempotent for every outcome.
cost: Job observation recorded the usage event first and updated the row second. If the row update failed, the next observation re-recorded the run. For a completed run the index dropped the duplicate; for a cancelled, failed or incomplete run (stored as `unexpected_response`) nothing did, so the spend report double-counted. A client cancel between the two writes did the same. Found by an audit after the code and its tests were green.
enforced_in: src/mcp_perplexity_pro/agent.py (observe_job checks for an existing event by request id and shields the row write), tests/test_job_observation.py (failed row update then re-observe, client cancel between the writes; both mutation-checked).
---

An index guarantees only the rows it covers. When the guard is partial, make the step itself
check for its own earlier effect, and test the non-covered outcomes (cancelled, failed,
incomplete) with a failure injected between the two writes.

---
name: a-cancel-cleanup-finally-must-not-await-before-releasing
kind: process-failure
trigger: Writing the cleanup of a task that holds a resource (a file descriptor, a byte budget, a lock) in a `finally` or `except` block that first awaits something (a shielded wait for worker threads, a gather) and only then releases the resource.
cost: In media-inputs `media_read._settle` re-raised the cancel after waiting for its threads, so `close_all` and `limiter.release` never ran when the cancel was level-triggered (FastMCP and anyio cancel the scope again on every await). A reproduction that cancelled twice while a reader was blocked leaked the descriptors and the byte budget; it was found as a Critical in review round 2 (commit 0243be8), after the earlier cancel tests, which cancel once, had passed.
enforced_in: tests/test_media_read.py::test_two_cancels_while_a_reader_is_blocked_still_clean_up (cancels twice while a reader thread is blocked and asserts `limiter.used == 0` and an unchanged descriptor count); the release sits in a `finally` nested outside the awaiting step.
---

Put the release in the outermost `finally`, and let the awaiting step (waiting for threads,
re-raising the cancel) run inside it. An `await` that can raise `CancelledError` before the
release line skips the release, and a cancel scope that is level-triggered will interrupt it
again. Test it with TWO cancels while the blocked work is still running: a single cancel
did not expose the broken order here.

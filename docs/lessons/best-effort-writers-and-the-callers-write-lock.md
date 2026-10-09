---
name: best-effort-writers-and-the-callers-write-lock
kind: process-failure
trigger: Specifying a "never fails the call" side-effect writer (usage log, audit trail) that opens its own database transaction on SQLite.
cost: The first spec said "record afterwards in its own unit of work" without saying when. SQLite has one writer lock: a recorder invoked while the tool's write unit is open waits for the busy timeout (5 s), loses the event and delays the reply, on every call. Caught only in spec review.
enforced_in: openspec/specs/usage-recording (Recording order), tests/test_usage_lock_order.py (hazard pinned, correct caller order, no write lock held across the upstream call), design.md D7 caller pattern.
---

Spec the ORDER, not just the isolation: resolve and commit what you need, make the upstream
call holding no write unit, record in its own unit, then do the tool's own write. Pin the
hazard with a test that calls the recorder inside an open write unit.

---
name: cleanup-tests-must-fail-when-cleanup-is-removed
kind: process-failure
trigger: Writing a test for shutdown, close, rollback or lock behavior where the observable result is a log line or an exit status.
cost: The first shutdown tests passed with the `aclose()` call deleted because the log line still printed; the two-process migration test passed with the file lock disabled because SQLite already serialised the writers. Both gave false confidence until a mutation check was run.
enforced_in: tests/fixture_server.py (writes a marker only after aclose/dispose really ran), tests/test_shutdown.py, tests/test_storage_migrate.py (non-empty database, torn-backup assertion).
---

After writing such a test, delete the thing it protects once, by hand, and confirm the test
goes red. Assert on the side effect (a file written after the close, an intact backup), not
on the message that claims the work happened.

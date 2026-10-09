---
name: docs-lie-probe-the-api-first
kind: process-failure
trigger: About to model a third-party API (types, fixtures, specs) from its documentation or OpenAPI file.
cost: Two documented claims were wrong against the live API (GET /v1/models needs auth and returns per-model pricing; the docs said neither). A spec written from the docs would have encoded both errors. The first probe outputs were also lost with the scratch directory and had to be recaptured.
enforced_in: tests/test_live_capture.py (recaptures fixtures, scans for keys), tests/fixtures/*.meta.json (capture date and endpoint), design.md "Observed API shapes".
---

Probe the real endpoint with the real key before writing a spec, record the responses as
fixtures in the repo straight away (scratch directories are session-scoped and get cleaned),
and let the fixtures, not the docs, define the models and the scenarios.

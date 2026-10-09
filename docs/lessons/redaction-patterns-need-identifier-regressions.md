---
name: redaction-patterns-need-identifier-regressions
kind: process-failure
trigger: Adding or widening a secret-redaction pattern, or storing a new kind of identifier (model id, project name) that goes through it.
cost: The key-shape regex (`pplx-` plus 8 key characters) also matched Perplexity's own model ids (`pplx-embed-v1-0.6b`, `pplx-decider-v1.1-27b`) and valid project names (`pplx-embeddings`), so stored usage rows would have collapsed every embedding and decider model into `[redacted]` and lost per-model spend. Found by a call-site audit before any caller existed; no test recorded such a name.
enforced_in: tests/test_usage_redaction_identity.py (every model constant in pricing.py survives redaction and storage; every name the project rule accepts survives the recorder), src/mcp_perplexity_pro/redaction.py (documented model-id exemption).
---

A redaction rule is only as safe as its list of things that must NOT be redacted. When a
pattern is added or widened, add a test that runs every documented identifier of the same
shape through it, and tie the project-name rule and the redactor to one definition of
"key-shaped".

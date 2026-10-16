Title: record-gate-review --artifact accepts a directory but records no digest, so every Gate 1 reads "unverifiable"

What happened: `record-gate-review <epic> --gate 1 ... --artifact openspec/changes/<id>` (a change DIRECTORY, which is what an OpenSpec Gate 1 reviews) prints "no content digest recorded for 1 of 1 artifact(s) - not a readable file, so later edits to them will read unverifiable rather than stale". The briefing then shows "⚠ unverifiable" on every Gate 1 line (it does for all of this repo's epics).

Why it matters: a Gate 1 verdict cannot go stale when the proposal, design, specs or tasks change afterwards, which is the property the digest exists to give. Here the specs were amended three times after the first review and the record could not say so.

Wanted: when --artifact is a directory, digest its files (sorted, recursive) so edits read stale; or document that the flag takes files and say which files an OpenSpec change should pass (proposal.md, design.md, tasks.md, each spec.md).

Repro: pm 0.52.0, any openspec-lane epic, `record-gate-review <id> --gate 1 --verdict pass --base-sha <a> --head-sha <b> --reviewer x --artifact openspec/changes/<id>`.

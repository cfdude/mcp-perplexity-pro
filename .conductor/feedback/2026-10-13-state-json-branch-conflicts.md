Parallel epic branches conflict on .conductor/state.json, PROJECT.md and render-stamp.json, and there is no verb to resolve it

What happened: two epic branches (one registering epics routing-modes-config, py-cli, pypi-publish; one registering py-agent-citation-fixes) were each cut from main, each ran add-epic/update-epic/record-gate-review, and each committed state.json. Merging the first then rebasing the second stopped with UU on .conductor/state.json, PROJECT.md and .conductor/render-stamp.json. state.json is engine-owned (hand-editing is forbidden by the rules block) and PROJECT.md is generated, so neither can be resolved by hand without breaking the rules.

What I did: aborted the rebase, reset the branch to main, kept only the openspec/ artifacts, and replayed every pm verb (add-epic, set-active, update-epic --attribute-commit for each commit, record-gate-review) by hand. Anything not replayed (a recorded gate, an attribution) was silently lost until I noticed.

Wanted: either a merge driver / `.gitattributes` entry shipped by /pm:init for state.json (union by epic id, last-writer-wins per field, then re-render), or a verb such as `merge-state <other-ref>` that applies another ref's epic records onto the current state and re-renders. Even a documented recipe for this case in the rules block would remove the guesswork.

Evidence: repo cfdude/mcp-perplexity-pro, pm 0.51.0, 2026-10-13; the rebase output named all three files UU.

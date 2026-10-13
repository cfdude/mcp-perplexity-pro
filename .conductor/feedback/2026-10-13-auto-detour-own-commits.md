Comment on cfdude/pm#213: more evidence from a Python migration repo.
11 AUTO-DETOUR rows in .conductor/detours.log, every one the active epic's own work
(fix/chore commits touching src/ and tests/, not the epic's openspec artifacts), e.g.
 py-usage-log   fix(usage): harden recorder edge cases
 py-usage-log   fix(storage): refuse mixed or unusable retained-table shapes
 py-agent-api   chore(tests): offline suite, ruff check and ruff format clean across the repo
 py-agent-api   fix(storage): return the connection when a unit of work is cancelled
Rows were written by the engine of the 0.4x era; not re-verified on 0.51.0 (no active epic now).
0.51.0 changelog only exempts commits touching the epic's own change artifacts, so fix/chore
commits to source still look like detours to the heuristic.

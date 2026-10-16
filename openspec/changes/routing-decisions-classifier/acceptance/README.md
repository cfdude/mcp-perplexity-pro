# Acceptance record: routing-decisions-classifier

## Task 2.1: tools/list size (measured 2026-10-15)

Method: `tests/test_tools_list_budget.py` builds a server through `build_server` with a dummy key
and one `tools/list` POST over HTTP on an ephemeral port (not the live pm2 app); the byte count is
`len(response.content)`. Budget: 59779 bytes.

| Server | Bytes |
|---|---|
| default (standard routing) | 56545 |
| dynamic, rules classifier | 56831 |
| dynamic, Decisions classifier | 57065 |

Combined size of both routing changes: the last recorded figure before them is 55512 bytes (eleven
tools, live server, 2026-10-13, agent-help acceptance, quoted in the test's comment). The dynamic
server with the Decisions classifier is 57065 bytes, +1553 bytes (+2.8%) over that figure, and
2714 bytes under the budget. The two measurements use different servers (live against test), so the
difference is an indication, not an exact attribution.

# Acceptance record: routing-rules-v1

## tools/list size (task 4.1)

Measured 2026-10-15 with one `tools/list` POST to a real HTTP runner (`tests/server_support.py`
`serving`, an ephemeral port, a dummy key, a temporary data directory), on the working tree of the
task 4.1 commit (parent `bfedb68`). Eleven tools in each case. The cap is 59779 bytes
(`tests/test_tools_list_budget.py`, parametrized over a default and a dynamic server).

| Server | Bytes | Against 59779 |
|---|---|---|
| default (`standard` mode) | 56367 | 3412 below |
| `dynamic` mode, no tier variables | 56581 | 3198 below |

For comparison, the same measurement on the parent commit (`bfedb68`, before the `perplexity_models`
routing fields and the reworded `tier` descriptions) gave 56024 for both modes. The growth is the
`preset` and `classifier` fields of the models routing section (+343 bytes in a default server) and
the dynamic wording of the instructions and the ask and chat descriptions (+214 more in dynamic mode).

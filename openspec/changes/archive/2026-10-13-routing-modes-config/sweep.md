# Call-site sweep and commit verification (tasks 6.1 and 6.2)

Derived with `rg` by the Gate 2 reviewer over e913422..8241060 (read from disk and git), not typed from memory.

| Rule | Call sites | Holds | Notes |
|---|---|---|---|
| `resolve()` is the only source of a route | `tools/ask.py`, `tools/chat.py` (send only) | yes | `AskOptions(` is built only there in `src/` |
| `build_request(AskOptions)` | `tools/ask.py`; `tools/chat.py` (four calls) | yes | the other `build_request` functions (`search`, `decisions`, `embeddings`) are unrelated |
| `DEFAULT_DEPTH`, `ASK_DEPTHS`, `LONG_DEPTHS` | only `routing.py` | yes | `research.py` keeps its own `RESEARCH_DEPTHS`: research is unchanged |
| readers of `options.preset` and `.model` | `agent.py` request build, `chat.py` row writes, `ask.py` | yes | a model route records preset null in the event and the chat row |
| `search` false with a depth refused | `agent.build_request` | yes | the "needs an explicit model" branch is gone |
| `routing` in results | `AskResult`, `ChatResult` | yes | absent from research, jobs, search, decide, embed |
| `register(server, settings)` | `tools/__init__.py`, `server.py` | yes | only ask and chat take `settings`; models reads it from the lifespan context |
| instructions and descriptions pure in settings | `server.py`, `description_sentence` | yes | |
| `dynamic` refused; `tier` outside custom refused; unknown tier refused | `settings.py`, `routing.py` | yes | tested |
| inverse: a routing variable that is set can be unset | defaults apply when unset | code yes, README in group 7 | the ignored-variable warning is tested |

Stale statements for group 7 (README, `CLAUDE.md`): `fast` named the default (README lines about depth), no routing section, example results lack `routing`, `CLAUDE.md` says the change is "proposed, not started", lacks `routing.py`, the routing settings and the new `tools/list` size; `ecosystem.example.cjs` lacks the optional variables.

Commit verification (`git show --stat` per commit): 1.1 `034b806`, 1.2 `8fb6256`, 2.1 `a5a250c`, 3.2 and 3.3 `fae2d0e`, 4.1 `15c0d09`, 5.x `9566962`, 6.4 `8241060` each contain the files their task claims. 3.1 `4d4d3a6` holds the tool, server and `tests/test_routing_tools.py` changes; the pinned-schema assertions moved in 2.1 (task text corrected).

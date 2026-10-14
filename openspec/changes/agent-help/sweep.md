# Call-site sweep and commit verification (tasks 6.1 and 6.2)

Derived with `rg` by the Gate 2 reviewer over ad16882..5071a24; no sibling site left unguarded.

| Rule | Sites | Holds |
|---|---|---|
| every tool has a help entry | 12 `register(` in `tools/`, 11 entries in `help_text.TOOLS` | yes; `test_every_registered_tool_has_a_curated_entry` and the help-page test cover help itself |
| hint on every `invalid_request` | all raise sites are `PerplexityError` inside a tool call; the only other `error_result` caller is the draining refusal (`internal_error`); framework `ValidationError` goes through `_classify` | yes (upstream 400/422 mapped to `invalid_request` also gets it, by the spec's wording) |
| no hint on other categories, on help's own errors, on a tool without an entry | `with_help_hint` | yes, one test each |
| instructions name help | `routing.instructions_text` | yes |
| five descriptions end with the pointer | `POINTER` in ask and chat, docstring sentence in embed, jobs, research | yes |
| size budget | `tests/test_tools_list_budget.py`, 11 tools at most 59779 bytes (55512 live) | yes |
| tool-count statements | tests updated; README, CLAUDE.md, CHANGELOG say "ten" | docs: group 7 |

Commit verification (`git show --stat`): 1.1 `b48984d`, 2.1 `3678b20`, 3.1 `bf55a94`, 4.1 `1954b1b`, 5.1 `06f075e`, 6.4 `5071a24` each contain the files their task claims.

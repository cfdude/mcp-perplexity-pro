# Call-site sweep (task 6.1), derived 2026-10-29 with `rg` at HEAD `dbb36e4`

| Rule | Call sites (rg) | Holds? |
|---|---|---|
| Agent requests carry `effort`, never `preset` | `rg '"preset"' src` finds only `usage.py:641` (the recorder's column dict, not a request). The two request builders are `agent.py:255` (build_request: ask, chat) and `agent.py:736` (research submit). `client.py:310` is `reasoning.effort` of the matrix probe, a different field by design (agent-ask "The effort field means the preset name"). The routing classifier and `matrix_refresh` build no Agent preset request | yes, everywhere |
| Preset table follows the documentation | the only reader of `PRESETS` is `tools/models.py:205`; the table is `catalog.py:72`; README table updated in 2.1 | yes |
| Every accepted decider name has a price, none redacted | `decisions.MODELS` is read at `decisions.py:181-182`; the only pricing caller is `decisions.py:323` through `pricing.decisions_cost_nano` (priced by the request's `body["model"]`); `DECISIONS_NANO_PER_INPUT_TOKEN` and `DECISIONS_PRICED_AS` are read only by `pricing.py:102-103` and the pricing tests; the redaction exemption is a prefix rule (`redaction.py`), pinned by `tests/test_usage_redaction_identity.py` | yes |
| An unknown name is never priced | `pricing.decisions_cost_nano` returns None through `_lookup` for a name in neither table; unreachable from the tool (MODELS validates first), tested on the pure function | yes |
| Stored data unchanged | `preset` columns (`storage/models.py`) and `usage.py:641` keep the preset names the request asked for; no migration | yes |

Inverses: a request field removed upstream (`preset` alias): already not sent; `effort` removed upstream would be a 400, passed through as an upstream error. A decider name retired upstream: 400 passes through, the price map keeps a dead name until edited (harmless, dated by `PRICES_AS_OF`).

Not changed and still stale (task 7.1): README model row "Both cost the same" (line 1053) and the 1138 example; `CLAUDE.md` rows; CHANGELOG.

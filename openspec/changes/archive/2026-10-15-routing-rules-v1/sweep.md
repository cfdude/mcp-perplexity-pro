# Call-site sweep (task 6.1)

Derived with `rg` on 2026-10-15 at `ed43579`; each rule, where it holds, where it does not.

## Callers of `resolve(` (`rg "resolve\(" src`, migrate.py's `Path.resolve` aside)
- `tools/ask.py:220`: passes `text=query`, `search`, the selectors. Holds.
- `tools/chat.py:574` (a send that names a selector, or any non-dynamic mode): resolves before any
  database access, as before. Holds.
- `tools/chat.py:237` (`_send`, a nameless dynamic send): resolves after the read-only lookup with
  `previous` and `search`. Holds.
- `tools/research.py` never calls `resolve`: research depths are presets, unchanged by every mode
  (spec "Research is unaffected"). Justified omission.
- `command.py` (CLI) reaches the tools in-process; no `resolve` of its own.

## Constructions of `Route(` (`rg "Route\(" src`)
- `routing.py:60` (`dynamic_route`) carries `reason` and `classifier`; lines 163 to 178 (custom
  tier, depth, model, defaults) leave both at their `None` defaults, which is the spec (reason and
  classifier set only when dynamic mode routed). Holds.

## Readers of `settings.routing`
- Every branch that knew `custom` also knows `dynamic` (resolve, `instructions_text`,
  `description_sentence`, `_routing_line`, the routing topic, the models section, the startup log,
  `ignored_routing_vars`, `_check_routing`). The only `custom`-only branches left are the ones that
  require three tier variables (settings validation) and the default-route text, both correct.

## `selected_by` and `reason`/`classifier` surfaces
- Result model `Routing` (ask.py), the help text and the tool/field descriptions name `classifier`;
  `rg "selected_by" src` shows no stale enumeration of the old four values. Holds.

## Stale text (docs group, not code)
- README.md lines 179, 201, 216 and CLAUDE.md lines 347 and 368 still say `dynamic` is reserved:
  owed to task 7.1 and tracked there.

## Inverses
- Dynamic mode on: set `PERPLEXITY_ROUTING=dynamic`; off: unset it (the default is `standard`).
  Tested by the settings tests in both directions.
- A classifier verdict is overridden by any explicit `depth`, `tier` or `model` (selector tests with
  the classifier patched to raise).
- The follow-up floor is left by naming a selector (explicit-selector scenario test).
- `high` and `xhigh` unreachable: `DYNAMIC_PRESETS` has no row for them; asserted by enumeration.

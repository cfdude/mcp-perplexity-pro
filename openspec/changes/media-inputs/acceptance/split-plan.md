# Split plan (media-inputs task 0.4)

Written 2026-11-11 before any code. Purpose: if `routing-v2`'s pre-registered evaluation fails
(design D18), `media-inputs` ships alone and the unwind is deletion, not redesign.

Derivation (mechanical): `rg -n "routing-v2|router|held model|required_input" openspec/changes/media-inputs src/`.
`src/` has no match yet (nothing is built); every match is in the change's own artifacts. The
`src/` side of this table is therefore a rule for the code tasks, and 6.1 re-runs the same `rg`
over `src/` and compares it with this file.

## The two seams

1. `required_input=` on `routing.resolve`: added by `routing-v2` 5.3a (router-free, media-owned,
   SURVIVES an unwind; default empty). Tasks 1.5, 2.3 and 3.1 build on 5.3a only, never on 5.4.
2. The held-model and router-substitution wording: lives only where listed below.

## Lines that name the router, a held model or `routing-v2`, and the replacement without `routing-v2`

| Where | What it says | Replacement when `routing-v2` is absent |
|---|---|---|
| `specs/media-attachments` "A router never picks an unknown model" (scenario, ~358) and the router halves of the requirement at ~338-352 | the router's choice needs `yes` | the gate checks `route.model` (or `preset_accepts` for a preset) on the existing `resolve`; no router choice exists |
| `specs/media-attachments` "A held model is kept only when it can take the kinds" (~362-367) | held model replaced by the router | deleted: no held model, no substitution |
| `specs/media-attachments` router-unavailable requirement (~374) | no pickable model fails before the Decisions request | deleted with the router; the single-route gate error remains |
| `specs/media-attachments` hint scenario (~404) | `routing-v2` text naming live same-family models replaces the plain hint | the media-owned DEFAULT stays (plain `model <id> is not served`, `attachment_hint` suppressed); only `routing-v2` 5.6(g)'s override is reverted |
| `specs/agent-chat` "Inherited kinds come from the stored notes", router-input scenario (~123) | the router is given required kinds | the gate is given the kinds instead (`inherited_kinds` survives, it feeds `resolve(required_input=...)`) |
| `specs/agent-chat` requirement that stores `tier` and `routed_model` (~159) | uses `routing-v2` migration `0006` columns | deleted; this change takes nothing from `0006` and task 3.2 asserts that |
| `specs/model-matrix` "The router asks which models accept a kind" (~334) and "The router functions are total and read-only" (~365) | `models_accepting` consumed by the router | `models_accepting` stays as a pure function (used by the gate's up-to-five accepting models in the error text); the "router" wording is edited to "callers" |
| `design.md` D13, D13a (held models, wiring order) | held-model rule, D13 call order with a router | D13 order without the router steps; D13a deleted |
| `design.md` D14 and the proposal "Apply order" | budget table assumes `routing-v2`'s 450-byte trim | standalone budget (design D14, "Standalone budget") applies; task 3.3's trim is waived only as that task states |
| `tasks.md` 1.4, 1.5, 2.3, 3.1, 3.3 ordering notes | "after `routing-v2` 5.x" | 5.3 and 5.3a are router-free and survive; no other dependency |

## Code rule for the build tasks

No `src/` line of this change may import or name `routing_select`, `routing_evidence`, the router,
or `chat_messages.tier`/`routed_model`; the only `routing-v2` contact points are `resolve(required_input=...)`,
`matrix.model_not_served` (owned here) and the hint seam whose default is owned here.

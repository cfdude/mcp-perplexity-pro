"""Regenerate the `inputs` of the packaged baseline from the 2026-10-30 sweep.

Path-free: the baseline file comes from the environment variable BASELINE_JSON (the packaged
`src/mcp_perplexity_pro/data/model_matrix_baseline.json`), the sweep from SWEEP_JSON (default:
`sweep.json` next to this script's parent directory). Run it with the project's interpreter so the
classifiers are the product's own, never a second copy:

    BASELINE_JSON=src/mcp_perplexity_pro/data/model_matrix_baseline.json \
        uv run python openspec/changes/media-inputs/acceptance/scripts/baseline_inputs.py

Rules (design D6, spec "The baseline's answer rules"): a 200 whose run status is `completed` or
`incomplete` is accepted; a 400 that `matrix.is_named_refusal` accepts is refused with its status;
every other answer (a not-served 400, the generic `invalid request`, a 429, a failed run) leaves the
kind unknown. Then ONE dated override: `xai/grok-4.7` accepts both kinds (re-probe of 2026-11-11,
`grok-4-7-investigation.md`), so the 2026-10-30 refusal is not recorded.

Entries not in the sweep (added later by hand, e.g. `openai/gpt-6.1-terra`) are left as they are;
a regeneration therefore keeps them but does not recreate any answer they were given by hand.
"""

import json
import os
import sys
from pathlib import Path

from mcp_perplexity_pro import matrix

SWEPT_AT = "2026-10-30T00:00:00Z"
OVERRIDE_AT = "2026-11-11T00:00:00Z"
OVERRIDES = {"xai/grok-4.7": ("image", "document")}  # both kinds accepted, probed 2026-11-11
KIND_OF = {"image": "image", "file": "document"}  # the sweep calls a document `file`


def classify(result: dict, model: str) -> tuple[str, int] | None:
    """('accepted' | 'refused', status) for an answered kind, None for an unknown one."""
    code = result.get("code")
    message = result.get("err") or ""
    if code == 200 and result.get("st") in ("completed", "incomplete"):
        return "accepted", 200
    if matrix.model_not_served(code or 0, message, model):
        return None
    if matrix.is_named_refusal(code or 0, message):
        return "refused", 400
    return None


def main() -> None:
    baseline_path = Path(os.environ["BASELINE_JSON"])
    sweep_path = Path(os.environ.get("SWEEP_JSON") or Path(__file__).resolve().parents[1] / "sweep.json")
    sweep = json.loads(sweep_path.read_text())
    # raw JSON in and out, so the diff of the baseline is only the added `inputs` objects
    raw = json.loads(baseline_path.read_text())
    models = raw["models"]
    for model_id, results in sweep.items():
        entry = models.get(model_id)
        if entry is None:
            print(f"not in the baseline, skipped: {model_id}", file=sys.stderr)
            continue
        inputs = matrix.Inputs()
        for sweep_kind, result in results.items():
            kind = KIND_OF[sweep_kind]
            answer = classify(result, model_id)
            if answer is None:
                continue
            outcome, status = answer
            if outcome == "accepted":
                inputs.accepted.append(kind)
            else:
                inputs.refused[kind] = status
            inputs.answers[kind] = status
            inputs.probed_at[kind] = SWEPT_AT
        if model_id in OVERRIDES:
            inputs = matrix.Inputs()
            for kind in OVERRIDES[model_id]:
                inputs.accepted.append(kind)
                inputs.answers[kind] = 200
                inputs.probed_at[kind] = OVERRIDE_AT
        inputs.accepted = [k for k in matrix.KINDS if k in inputs.accepted]
        inputs.source = "baseline" if inputs.accepted or inputs.refused else "unprobed"
        entry["inputs"] = inputs.model_dump(mode="json")
    baseline_path.write_text(json.dumps(raw, indent=1) + "\n")
    counts = {
        kind: (
            sum(kind in e["inputs"]["accepted"] for e in models.values() if "inputs" in e),
            sum(kind in e["inputs"]["refused"] for e in models.values() if "inputs" in e),
        )
        for kind in matrix.KINDS
    }
    print("accepted, refused per kind:", counts)


if __name__ == "__main__":
    main()

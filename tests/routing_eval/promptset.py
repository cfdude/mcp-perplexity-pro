"""Reading the evaluation set and the two frozen hashes (routing-v2 task 3.2).

The set lives in ``tests/fixtures/routing_prompts.json`` (the labeled set of the rules classifier,
extended): a prompt with a ``split`` belongs to the evaluation. ``prompt_set.sha256`` is the
SHA-256 of that file's bytes and ``heldout_split.sha256`` the SHA-256 of the assignment (one
``id<TAB>split`` line per evaluation prompt, sorted by id), both committed in the same commit as
the set and never changed after the first scored run.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_PATH = ROOT / "tests" / "fixtures" / "routing_prompts.json"
PILOT_PATH = ROOT / "tests" / "fixtures" / "routing_eval_pilot.json"
ACCEPTANCE = ROOT / "openspec" / "changes" / "routing-v2" / "acceptance"
PROMPT_HASH_PATH = ACCEPTANCE / "prompt_set.sha256"
SPLIT_HASH_PATH = ACCEPTANCE / "heldout_split.sha256"
CLASSES = ("coding", "reasoning", "browsing")
CHECK_KINDS = ("exact", "regex", "number")
MAX_CRITERIA = 5


def load_prompts() -> list[dict[str, Any]]:
    return json.loads(PROMPTS_PATH.read_text())


def evaluation_prompts(prompts: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The prompts that belong to the evaluation: those that carry a ``split``."""
    return [p for p in (prompts if prompts is not None else load_prompts()) if "split" in p]


def prompt_set_digest() -> str:
    return hashlib.sha256(PROMPTS_PATH.read_bytes()).hexdigest()


def split_text(prompts: list[dict[str, Any]] | None = None) -> str:
    rows = sorted(evaluation_prompts(prompts), key=lambda p: p["id"])
    return "".join(f"{p['id']}\t{p['split']}\n" for p in rows)


def split_digest(prompts: list[dict[str, Any]] | None = None) -> str:
    return hashlib.sha256(split_text(prompts).encode()).hexdigest()


def recorded(path: Path) -> str:
    """The digest a ``.sha256`` file records (its first token)."""
    return path.read_text().split()[0]


def is_machine_checkable(item: dict[str, Any]) -> bool:
    return "check" in item["eval"]


def shape_problems(item: dict[str, Any]) -> list[str]:
    """What is wrong with an ``eval`` block: exactly one of ``check`` (kind ``exact``, ``regex``
    or ``number``) or ``rubric`` (one to five binary criteria). No field can hold code."""
    ev = item.get("eval")
    if not isinstance(ev, dict) or set(ev) not in ({"check"}, {"rubric"}):
        return ["eval must hold exactly one of check or rubric"]
    if "rubric" in ev:
        rubric = ev["rubric"]
        ok = isinstance(rubric, list) and 1 <= len(rubric) <= MAX_CRITERIA
        if not ok or not all(isinstance(c, str) and c.strip() for c in rubric):
            return [f"rubric must be 1 to {MAX_CRITERIA} non-empty strings"]
        return []
    check = ev["check"]
    kind = check.get("kind") if isinstance(check, dict) else None
    if kind not in CHECK_KINDS:
        return [f"check kind must be one of {CHECK_KINDS}"]
    if kind == "exact":
        want = {"kind", "value"}
        if set(check) != want or not isinstance(check["value"], str) or not check["value"]:
            return ["exact needs a non-empty string value"]
    elif kind == "regex":
        if set(check) != {"kind", "pattern"} or not isinstance(check["pattern"], str):
            return ["regex needs a pattern"]
        try:
            re.compile(check["pattern"])
        except re.error as exc:
            return [f"regex does not compile: {exc}"]
    else:
        number = (int, float)
        bad = set(check) != {"kind", "value", "tolerance"}
        bad = (
            bad or isinstance(check.get("value"), bool) or isinstance(check.get("tolerance"), bool)
        )
        bad = bad or not isinstance(check.get("value"), number)
        bad = bad or not isinstance(check.get("tolerance"), number) or check["tolerance"] < 0
        if bad:
            return ["number needs a numeric value and a non-negative tolerance"]
    return []

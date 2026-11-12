"""The seeded rule that splits the evaluation set into ``main`` and ``heldout`` (routing-v2 3.2).

Fixed before the router exists, so nothing can be tuned to the held-out prompts. Inside each task
class the prompt ids are ordered by ``sha256(SEED + ":" + id)`` and the first ``HELDOUT_PER_CLASS``
are held out; the rest are ``main``. The rule depends on ids only, never on a prompt's text, so
editing a prompt cannot move it between subsets (the prompt-set hash catches the edit instead).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping

SEED = "routing-eval-split-v1"
HELDOUT_PER_CLASS = 5
MAIN_PER_CLASS = 15


def _rank(prompt_id: str) -> str:
    return hashlib.sha256(f"{SEED}:{prompt_id}".encode()).hexdigest()


def assign(ids_by_class: Mapping[str, Iterable[str]]) -> dict[str, str]:
    """Map each prompt id to ``main`` or ``heldout``, class by class."""
    out: dict[str, str] = {}
    for ids in ids_by_class.values():
        ordered = sorted(ids, key=lambda i: (_rank(i), i))
        for position, prompt_id in enumerate(ordered):
            out[prompt_id] = "heldout" if position < HELDOUT_PER_CLASS else "main"
    return out

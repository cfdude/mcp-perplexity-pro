"""``POST /v1/decisions`` payload (shape from ``tests/fixtures/decisions_*``).

Parsing is tolerant (design D6): each answer, ``model`` and ``usage`` are kept as received, so a
billed 200 is never lost to a schema quibble. Only ``answers``, an object, is required.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class DecisionsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    answers: dict[str, Any]
    model: Any = None
    usage: Any = None

"""``POST /v1/embeddings`` payload (shape from ``tests/fixtures/embeddings_*``).

Parsing is tolerant (design D8): ``data`` items, ``model`` and ``usage`` are kept as received, so
a billed 200 is never lost to a schema quibble. Only ``data``, a list, is required.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class EmbeddingsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: list[Any]
    model: Any = None
    usage: Any = None

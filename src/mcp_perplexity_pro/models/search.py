"""``POST /search`` payload (shape from ``tests/fixtures/search_*``).

Parsing is tolerant (design D7): items are NOT typed, so a null title, a numeric date or a
non-object item in a billed 200 cannot fail the parse. ``search.digest`` reads them defensively.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    results: list[Any]
    id: Any = None

"""``GET /v1/models`` payload.

Every model accepts unknown fields (``extra="allow"``). Only ``data`` (envelope) and ``id``
(per entry) are required; ``owned_by`` and every price are optional because the API omits
``cache_write`` for 30 of 52 recorded models and a model may arrive without pricing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ModelPricing(BaseModel):
    model_config = ConfigDict(extra="allow")

    input: float | None = None
    output: float | None = None
    cache_read: float | None = None
    cache_write: float | None = None
    unit: str | None = None


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    owned_by: str | None = None
    pricing: ModelPricing | None = None


class ModelList(BaseModel):
    model_config = ConfigDict(extra="allow")

    data: list[ModelEntry]

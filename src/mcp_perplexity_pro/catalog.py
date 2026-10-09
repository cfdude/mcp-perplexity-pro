"""The model catalog: a TTL cache over ``GET /v1/models`` (design D11). No MCP imports.

* One upstream request serves every caller on a cold cache (single flight): concurrent callers
  join the request already running instead of starting their own.
* A cached list younger than ``ttl`` is served without a request; ``refresh=True`` bypasses it.
* When the live request fails with ``rate_limited``, ``upstream_failure`` or ``network_timeout``
  and a cached list younger than ``max_stale`` exists, that list is returned marked stale. Any
  other failure (``authentication``, ``forbidden``, ...) is raised: a revoked key must not keep
  working through the cache.
* The documented preset table is a constant kept apart from the live list.

The clock is injected (wall-clock seconds, ``time.time``: a monotonic clock stops while the
machine sleeps, so a cache would never age across a laptop's lid-closed night) so tests never
sleep.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, Field

from mcp_perplexity_pro.errors import PerplexityError

if TYPE_CHECKING:
    from mcp_perplexity_pro.client import PerplexityClient
    from mcp_perplexity_pro.models import ModelList

# The only failures a cached list may cover for (a transient upstream problem, not a verdict
# about the caller's credentials or request).
STALE_OK_CATEGORIES = frozenset({"rate_limited", "upstream_failure", "network_timeout"})


class Pricing(BaseModel):
    """Prices exactly as the API reported them; a field the API omitted is null."""

    input: Annotated[float | None, Field(description="Input price per unit")] = None
    output: Annotated[float | None, Field(description="Output price per unit")] = None
    cache_read: Annotated[float | None, Field(description="Cache-read price per unit")] = None
    cache_write: Annotated[float | None, Field(description="Cache-write price per unit")] = None
    unit: Annotated[str | None, Field(description="Price unit, e.g. usd_per_1m_tokens")] = None


class CatalogModel(BaseModel):
    id: Annotated[str, Field(description="Model id, e.g. anthropic/claude-sonnet-4-5")]
    provider: Annotated[str | None, Field(description="The API's owned_by value")] = None
    pricing: Annotated[Pricing, Field(description="Prices; all null when none were reported")]


class Preset(BaseModel):
    name: Annotated[str, Field(description="Agent API preset name")]
    model: Annotated[str, Field(description="Model the preset is documented to resolve to")]


class PresetSection(BaseModel):
    source: Annotated[Literal["documentation"], Field(description="Not live data")] = (
        "documentation"
    )
    as_of: Annotated[str, Field(description="Date the table was recorded (YYYY-MM-DD)")]
    presets: list[Preset]
    note: str


# Sources: https://docs.perplexity.ai/docs/agent-api/presets.md ("current preset values"), read
# 2026-10-06 and re-read 2026-10-09. Only ``fast`` was also observed live (2026-10-09, resolved to
# openai/gpt-6-luna); the other four are documentation-only (design.md, "Preset sources").
PRESETS = PresetSection(
    as_of="2026-10-06",
    presets=[
        Preset(name="fast", model="openai/gpt-6-luna"),
        Preset(name="low", model="openai/gpt-6-luna"),
        Preset(name="medium", model="openai/gpt-6-luna"),
        Preset(name="high", model="openai/gpt-6-sol"),
        Preset(name="xhigh", model="anthropic/claude-opus-5-5"),
    ],
    note=(
        "Taken from Perplexity's documentation, not from the live API. Presets are dynamic and "
        "unversioned, so the model behind a name can change; check the resolved model in a "
        "response."
    ),
)


@dataclass(frozen=True)
class Listing:
    """A catalog read: the full model list plus how fresh it is."""

    models: list[CatalogModel]
    age_seconds: float
    stale: bool

    @property
    def providers(self) -> list[str]:
        return sorted({m.provider for m in self.models if m.provider})

    def for_provider(self, provider: str | None) -> list[CatalogModel]:
        """Models whose provider equals ``provider`` ignoring case; all models when ``None``."""
        if provider is None:
            return list(self.models)
        wanted = provider.casefold()
        return [m for m in self.models if m.provider and m.provider.casefold() == wanted]


def to_catalog_models(payload: ModelList) -> list[CatalogModel]:
    models = []
    for entry in payload.data:
        pricing = entry.pricing.model_dump() if entry.pricing else {}
        models.append(
            CatalogModel(
                id=entry.id,
                provider=entry.owned_by,
                pricing=Pricing(**{k: pricing.get(k) for k in Pricing.model_fields}),
            )
        )
    return models


class Catalog:
    def __init__(
        self,
        client: PerplexityClient,
        *,
        ttl: float,
        max_stale: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self._ttl = ttl
        self._max_stale = max_stale
        self._clock = clock
        self._models: list[CatalogModel] | None = None
        self._fetched_at = 0.0
        self._inflight: asyncio.Task[list[CatalogModel]] | None = None

    def _age(self) -> float:
        return self._clock() - self._fetched_at

    async def get(self, *, refresh: bool = False) -> Listing:
        if not refresh and self._models is not None and 0 <= self._age() < self._ttl:
            return Listing(self._models, self._age(), stale=False)
        try:
            models = await self._fetch_shared()
        except PerplexityError as exc:
            if (
                exc.category in STALE_OK_CATEGORIES
                and self._models is not None
                and 0 <= self._age() < self._max_stale
            ):
                return Listing(self._models, self._age(), stale=True)
            raise
        return Listing(models, self._age(), stale=False)

    async def _fetch_shared(self) -> list[CatalogModel]:
        """Join the request already running, or start the one every other caller will join."""
        if self._inflight is None:
            task = asyncio.ensure_future(self._fetch())
            task.add_done_callback(self._finished)
            self._inflight = task
        # shield: one caller being cancelled must not cancel the request the others wait on
        return await asyncio.shield(self._inflight)

    def _finished(self, task: asyncio.Task[list[CatalogModel]]) -> None:
        self._inflight = None
        if not task.cancelled():
            task.exception()  # mark retrieved; waiters still receive it

    async def _fetch(self) -> list[CatalogModel]:
        models = to_catalog_models(await self._client.list_models())
        self._models = models
        self._fetched_at = self._clock()
        return models

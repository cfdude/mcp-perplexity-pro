"""Async client for the Perplexity API.

Every failure leaves this module as a ``PerplexityError``: FastMCP would otherwise replace an
escaping ``httpx2`` error with its own fixed message and the category would be lost.
"""

from __future__ import annotations

from typing import Any, TypeVar

import httpx2
from pydantic import BaseModel, ValidationError

from mcp_perplexity_pro.errors import PerplexityError, error_from_response
from mcp_perplexity_pro.models import ModelList
from mcp_perplexity_pro.settings import Settings

M = TypeVar("M", bound=BaseModel)

_TIMEOUT_NAMES = (
    (httpx2.ConnectTimeout, "connect"),
    (httpx2.ReadTimeout, "read"),
    (httpx2.WriteTimeout, "write"),
    (httpx2.PoolTimeout, "pool"),
)


class PerplexityClient:
    """Bearer-authenticated JSON client.

    ``transport`` (for tests, an ``httpx2.MockTransport``) or ``http`` (a ready
    ``httpx2.AsyncClient`` the caller owns) may be injected; otherwise the client builds and
    owns its own. The base URL and credential come from settings on every request, so an
    injected client needs no configuration of its own.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx2.AsyncClient | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._owns_http = http is None
        self._http = http or httpx2.AsyncClient(transport=transport)
        self._timeout = httpx2.Timeout(
            connect=settings.connect_timeout,
            read=settings.read_timeout,
            write=settings.read_timeout,
            pool=settings.connect_timeout,
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _secrets(self) -> tuple[str, ...]:
        return (self._settings.api_key.get_secret_value(),)

    def _timeout_error(self, exc: httpx2.TimeoutException) -> PerplexityError:
        kind = next((name for cls, name in _TIMEOUT_NAMES if isinstance(exc, cls)), "request")
        limit = getattr(self._timeout, kind, None)
        seconds = f" ({limit:g}s)" if isinstance(limit, int | float) else ""
        return PerplexityError(
            "network_timeout",
            f"The Perplexity API {kind} timeout{seconds} elapsed.",
            secrets=self._secrets(),
        )

    async def _send(self, method: str, path: str, json: Any) -> httpx2.Response:
        try:
            return await self._http.request(
                method,
                self._settings.base_url + path,
                json=json,
                headers={
                    "Authorization": f"Bearer {self._settings.api_key.get_secret_value()}",
                    "Accept": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx2.TimeoutException as exc:
            raise self._timeout_error(exc) from None
        except httpx2.HTTPError as exc:
            raise PerplexityError(
                "upstream_failure",
                f"Could not reach the Perplexity API ({type(exc).__name__}).",
                secrets=self._secrets(),
            ) from None

    async def request_json(self, method: str, path: str, json: Any = None) -> Any:
        """Send one request and return the parsed JSON body of a 2xx response."""
        response = await self._send(method, path, json)
        if response.status_code >= 300:
            raise error_from_response(response.status_code, response.text, secrets=self._secrets())
        try:
            return response.json()
        except ValueError:
            raise PerplexityError(
                "unexpected_response",
                f"{path} returned a body that is not JSON.",
                status=response.status_code,
            ) from None

    def _parse(self, model: type[M], data: Any, path: str) -> M:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(part) for part in first["loc"]) or "<body>"
            raise PerplexityError(
                "unexpected_response",
                f"{path} response is missing or has an invalid required field {field!r}.",
            ) from None

    async def list_models(self) -> ModelList:
        path = "/v1/models"
        return self._parse(ModelList, await self.request_json("GET", path), path)

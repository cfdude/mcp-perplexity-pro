"""Async client for the Perplexity API.

Every failure leaves this module as a ``PerplexityError``: FastMCP would otherwise replace an
escaping ``httpx2`` error with its own fixed message and the category would be lost.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import httpx2
from pydantic import BaseModel, ValidationError

from mcp_perplexity_pro.errors import PerplexityError, error_from_response
from mcp_perplexity_pro.models import ModelList
from mcp_perplexity_pro.settings import Settings

M = TypeVar("M", bound=BaseModel)

logger = logging.getLogger(__name__)

_REQUEST_ID_HEADERS = ("x-request-id", "request-id")

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
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sleep = sleep
        self._jitter = jitter
        self._clock = clock
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

    @staticmethod
    def _log_call(
        method: str,
        path: str,
        attempt: int,
        started: float,
        response: httpx2.Response | None,
    ) -> None:
        """One diagnostic record per upstream call; never a body, header value or credential."""
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        status = response.status_code if response is not None else None
        request_id = None
        if response is not None:
            request_id = next(
                (response.headers[h] for h in _REQUEST_ID_HEADERS if h in response.headers), None
            )
        logger.info(
            "upstream %s %s -> %s request_id=%s attempt=%d elapsed_ms=%s",
            method,
            path,
            status if status is not None else "no response",
            request_id,
            attempt,
            elapsed_ms,
            extra={
                "http_method": method,
                "http_path": path,
                "http_status": status,
                "request_id": request_id,
                "attempt": attempt,
                "elapsed_ms": elapsed_ms,
            },
        )

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff (1s, 2s, 4s ...) scaled by jitter in [0.5, 1.5), capped."""
        delay = 2.0 ** (attempt - 1) * (0.5 + self._jitter())
        return min(delay, self._settings.max_retry_wait)

    def _retry_after(self, value: str | None) -> float | None:
        """Seconds from a ``Retry-After`` header (delta-seconds or HTTP date), else None."""
        if value is None:
            return None
        value = value.strip()
        try:
            seconds = float(value)
        except ValueError:
            try:
                when = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            seconds = (when - self._clock()).total_seconds()
        if seconds != seconds or seconds == float("inf"):  # NaN or infinite
            return None
        return max(seconds, 0.0)

    async def request_json(self, method: str, path: str, json: Any = None) -> Any:
        """Send a request, applying the retry rules, and return the parsed 2xx JSON body.

        A POST creates work and is replayed only after a 429 (never billed) or a connect
        failure (provably not sent). A GET is also retried on 5xx, timeouts and any
        connection failure. Every other failure is raised as ``PerplexityError`` at once.
        """
        is_read = method.upper() == "GET"
        attempts = self._settings.max_attempts
        for attempt in range(1, attempts + 1):
            wait: float | None = None  # set when this attempt may be retried
            started = time.monotonic()
            try:
                response = await self._send(method, path, json)
            except httpx2.TimeoutException as exc:
                self._log_call(method, path, attempt, started, None)
                error = self._timeout_error(exc)
                not_sent = isinstance(exc, httpx2.ConnectTimeout)
                retryable = is_read or not_sent
            except httpx2.HTTPError as exc:
                self._log_call(method, path, attempt, started, None)
                error = PerplexityError(
                    "upstream_failure",
                    f"Could not reach the Perplexity API ({type(exc).__name__}).",
                    secrets=self._secrets(),
                )
                retryable = is_read or isinstance(exc, httpx2.ConnectError)
            else:
                self._log_call(method, path, attempt, started, response)
                if response.status_code < 300:
                    try:
                        return response.json()
                    except ValueError:
                        raise PerplexityError(
                            "unexpected_response",
                            f"{path} returned a body that is not JSON.",
                            status=response.status_code,
                        ) from None
                error = error_from_response(
                    response.status_code, response.text, secrets=self._secrets()
                )
                if response.status_code == 429:
                    asked = self._retry_after(response.headers.get("retry-after"))
                    if asked is not None and asked > self._settings.max_retry_wait:
                        raise error  # waiting this out is worse than failing now
                    wait = asked
                    retryable = True
                else:
                    retryable = is_read and response.status_code >= 500

            if not retryable or attempt == attempts:
                raise error
            await self._sleep(wait if wait is not None else self._backoff(attempt))
        raise AssertionError("unreachable")  # pragma: no cover

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

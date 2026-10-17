"""The one costed-call sequence (design D6): the recorder contract of ``CLAUDE.md``.

1. validate the project name (pure);
2. commit the project in a short write unit (``resolve_project=False`` skips it);
   ``unscoped=True`` skips steps 1 and 2 and records the event under no project (a background
   task of the server, such as the model matrix probe, has no project to name);
3. the timed upstream call, holding NO write unit;
4. ``record_usage`` (its own unit) while no write unit is open: a failure is recorded with its
   category and re-raised; a response is recorded as the caller's interpreter says.

The interpreter (``record``) runs after the upstream call returned, when the spend has already
happened, so it must never raise. ``costed_call`` defends anyway: an exception out of it is
logged, the call is recorded as ``unexpected_response`` with no usage, and that category is
raised. This module and the job observation are the only ``record_usage`` call sites.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.redaction import redact_text
from mcp_perplexity_pro.storage.projects import (
    DEFAULT_PROJECT,
    get_or_create_project,
    validate_project_name,
)
from mcp_perplexity_pro.storage.session import unit_of_work
from mcp_perplexity_pro.usage import Usage, format_usd, record_usage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Recording:
    """What the interpreter says about a response: the event to store.

    ``usage`` is the recorder's own parameter type: a parsed ``Usage``, the raw usage mapping
    (the recorder parses it) or ``None``.
    """

    status: str
    usage: Usage | Mapping | None = None
    model: str | None = None
    preset: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class Costed[T]:
    """The result, the measured latency, the project name used (``None`` for an unscoped call),
    the status the event carries (``None`` when no event was attempted) and the interpreted
    ``Recording``."""

    result: T
    latency_ms: int
    project: str | None
    status: str | None
    recording: Recording | None


def cost_fields(usage: Usage | Mapping | None) -> tuple[str | None, str]:
    """``(cost_usd, cost_source)`` of a recorded usage, as a tool's output carries them."""
    if isinstance(usage, Usage) and usage.cost_source != "none":
        return format_usd(usage.cost_nano_usd), usage.cost_source
    return None, "none"


def _ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


async def costed_call[T](
    app: Any,
    *,
    tool: str,
    api: str,
    project: str | None,
    preset: str | None,
    call: Callable[[], Awaitable[T]],
    record: Callable[[T], Recording | None],
    resolve_project: bool = True,
    unscoped: bool = False,
) -> Costed[T]:
    """Run ``call`` and record it. ``app`` is the ``AppContext`` (``.settings``, ``.engine``).

    ``unscoped`` records the event under no project: the name is neither validated nor used,
    no project row is created or touched (whatever ``resolve_project`` says) and the result's
    ``project`` is ``None``. Every other caller leaves it false and gets a project name back.
    """
    name: str | None = None if unscoped else validate_project_name(project or DEFAULT_PROJECT)
    if name is not None and resolve_project:
        async with unit_of_work(app.engine) as session:  # short, committed before the call
            await get_or_create_project(session, name)
    secrets = (app.settings.api_key.get_secret_value(),)
    started = time.monotonic()
    try:
        result = await call()
    except PerplexityError as exc:
        await record_usage(
            app.engine,
            tool=tool,
            api=api,
            status=exc.category,
            preset=preset,
            project=name,
            latency_ms=_ms(started),
            secrets=secrets,
        )
        raise
    latency = _ms(started)
    broken = False
    try:
        recording = record(result)
    except Exception as exc:  # the interpreter is total by contract: a bug must not hide a bill
        logger.error("costed call: interpreter failed: %s", redact_text(repr(exc), secrets))
        recording, broken = Recording("unexpected_response"), True
    if recording is not None:
        await record_usage(
            app.engine,
            tool=tool,
            api=api,
            status=recording.status,
            usage=recording.usage,
            model=recording.model,
            preset=recording.preset,
            request_id=recording.request_id,
            project=name,
            latency_ms=latency,
            secrets=secrets,
        )
    if broken:
        raise PerplexityError(
            "unexpected_response", "The response could not be interpreted.", secrets=secrets
        )
    return Costed(
        result=result,
        latency_ms=latency,
        project=name,
        status=None if recording is None else recording.status,
        recording=recording,
    )

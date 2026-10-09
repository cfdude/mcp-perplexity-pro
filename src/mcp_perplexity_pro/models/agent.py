"""``POST /v1/agent`` and ``GET /v1/agent/{id}`` payloads (shapes from ``tests/fixtures/agent_*``).

Parsing is tolerant (design D5): every model keeps unknown fields, and only ``id`` and
``status`` of a run are required. ``output`` is typed ``Any`` so that a value the API sends in
a shape nobody recorded (an object, a string) is kept for ``agent.digest`` instead of failing
the whole parse, and a spend-bearing response is never lost to a schema quibble.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class AgentRun(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    status: str
    model: str | None = None
    usage: Any = None
    error: Any = None
    incomplete_details: Any = None
    output: Any = []


class CancelResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    response_id: str
    status: str

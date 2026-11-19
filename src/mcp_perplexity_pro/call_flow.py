"""The shared order of a model call, and the three hooks input attachments plug into.

Every ask and every chat send resolves its route in the same fixed order (routing design D16,
attachments design D13):

1. the selector and tier errors (``routing.check_selectors``);
2. the attachment-parse hook (``parse_attachments``: the kinds of the call, a bad attachment fails
   here, before any model is resolved);
3. a provisional resolve and the validation of every option (a bad option always beats a refusal
   of the steps below);
4. the real resolve with the call's kinds (``resolve(required_input=kinds)``);
5. the gate hook (``gate_route``: may the final route carry these kinds?);
6. when the Decisions classifier applies, its request, then a second resolve; and when that second
   resolve changed the route, the gate hook again on the FINAL route.

Nothing here depends on how a model is chosen. ``tools/ask.py`` and ``tools/chat.py`` call the
hooks through THIS module (never ``from call_flow import ...``) so a test can replace one and
assert where it ran.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from mcp_perplexity_pro import media, media_read
from mcp_perplexity_pro.routing import Route

logger = logging.getLogger(__name__)


def parse_attachments(attachments: Any = None) -> frozenset[str]:
    """The input kinds (a subset of ``image`` and ``document``) a call's attachments need, after
    parsing and local validation (no file is read); a bad attachment raises ``invalid_request``.
    No attachments need no kinds."""
    return frozenset(item.kind for item in media.parse_attachments(attachments))


@asynccontextmanager
async def held(app: Any, items: Sequence[media.Attachment], text: str) -> AsyncIterator[list]:
    """Read the call's path items and hold the call's share of the process-wide byte budget until
    the block exits; yields every item with its bytes. Nothing is read for a call with none."""
    policy = app.attach.policy(app.settings)
    async with media_read.hold_attachments(items, policy, app.attach.limiter, text=text) as loaded:
        for item in loaded:
            logger.debug("%s", media.log_line(item))
        yield loaded


def gate_route(app: Any, route: Route, kinds: frozenset[str]) -> None:
    """Refuse (``invalid_request``) a FINAL route that cannot carry ``kinds``; called once on the
    route of the real resolve and again on the route of the second resolve when that changed it.
    A no-op until attachments exist."""
    return None


def inherited_kinds(chat: Any) -> frozenset[str]:
    """The input kinds named by the earlier turns of ``chat`` (its stored attachment notes). A
    no-op returning no kinds until attachments exist; attachments own it from here on."""
    return frozenset()


def required_kinds(new: frozenset[str], chat: Any, *, replay: bool) -> frozenset[str]:
    """The kinds a chat send must be able to carry: the new message's kinds plus, for a CHAINED
    send, the kinds of the chat's earlier turns (the API keeps those files); for a REPLAY only the
    new kinds, because a replay resends no earlier file."""
    if replay or chat is None:
        return new
    return new | inherited_kinds(chat)

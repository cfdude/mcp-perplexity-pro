"""The stored note of a chat turn's attachments, and what a chat reads back from it (spec
``agent-chat``, design D7 and D10).

Pure: no database, no network. A turn with attachments is stored as its text, a newline and one
trailer line ``[attachments: <item>; <item>]``. Only the server writes a trailer: a line of the
user's own that begins ``[attachments:`` is stored with a leading backslash, and the strict parser
below accepts nothing but the item grammar ``media.note_item`` writes, so the last line of a
stored message is a genuine trailer or none. Lines are split on ``\\n`` only, never on the other
Unicode line separators.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Sequence

from mcp_perplexity_pro import media
from mcp_perplexity_pro.errors import PerplexityError

PREFIX = "[attachments:"
RESTART = "restart"

_TYPE = r"[a-z]+/[a-z0-9.+-]+"
_FILE = re.compile(
    rf"^(?P<name>[^;()\[\]\n]{{1,{media.MAX_NOTE_NAME}}}) \((?P<type>{_TYPE}), "
    r"(?P<bytes>\d+) bytes, sha256 (?P<sha>[0-9a-f]{12})\)$"
)
_URL = re.compile(
    rf"^(?P<host>[A-Za-z0-9._-]+) \((?P<type>{_TYPE}), url sha256 (?P<sha>[0-9a-f]{{12}})\)$"
)
_MORE = re.compile(
    r"^\+(?P<n>\d+) more: (?P<docs>\d+) documents, (?P<imgs>\d+) images, (?P<bytes>\d+) bytes$"
)
_TRAILER = re.compile(r"^\[attachments: (?P<body>[^\n]*)\]$")


@dataclasses.dataclass(frozen=True)
class Trailer:
    """What one stored trailer says: whether its turn restarted the chain, how many items it
    lists (hidden ones included), and the documents, images and document bytes among them."""

    restart: bool = False
    items: int = 0
    documents: int = 0
    images: int = 0
    document_bytes: int = 0

    @property
    def kinds(self) -> frozenset[str]:
        out = set()
        if self.documents:
            out.add("document")
        if self.images:
            out.add("image")
        return frozenset(out)


def escape_user_text(text: str) -> str:
    """A line of the user's text that begins ``[attachments:`` gets a leading backslash, on every
    line, so no stored line of a user message can be mistaken for a trailer."""
    if PREFIX not in text:
        return text
    return "\n".join("\\" + line if line.startswith(PREFIX) else line for line in text.split("\n"))


def stored_text(text: str, trailer: str | None, *, restart: bool = False) -> str:
    """The user message as stored: the escaped text, then the trailer when the turn has one. A
    ``restart`` turn (a replay in a chat that already has notes) always has one; with no items it
    is exactly ``[attachments: restart]``."""
    escaped = escape_user_text(text)
    if restart:
        trailer = f"{PREFIX} {RESTART}]" if trailer is None else _with_restart(trailer)
    if trailer is None:
        return escaped
    return f"{escaped}\n{trailer}"


def _with_restart(trailer: str) -> str:
    return f"{PREFIX} {RESTART}; " + trailer[len(PREFIX) + 1 :]


def parse_trailer(content: str) -> Trailer | None:
    """The trailer on the last line of a stored user message, or ``None`` when the last line is
    not a genuine trailer (no trailer, an escaped line, or one item that breaks the grammar)."""
    match = _TRAILER.match(content.rsplit("\n", 1)[-1])
    if match is None:
        return None
    parts = match.group("body").split("; ")
    restart = parts[0] == RESTART
    if restart:
        parts = parts[1:]
    items = documents = images = size = 0
    for part in parts:
        found = _FILE.match(part) or _URL.match(part)
        if found is not None:
            kind = _kind_of(found.group("type"))
            if kind is None:
                return None
            items += 1
            if kind == "document":
                documents += 1
                size += int(found.groupdict().get("bytes") or 0)
            else:
                images += 1
            continue
        more = _MORE.match(part)
        if more is None:
            return None
        items += int(more.group("n"))
        documents += int(more.group("docs"))
        images += int(more.group("imgs"))
        size += int(more.group("bytes"))  # the tail's bytes cover every hidden item: conservative
    return Trailer(restart, items, documents, images, size)


def _kind_of(media_type: str) -> str | None:
    entry = media.SUPPORTED.get(media.ALIASES.get(media_type, media_type))
    return entry[0] if entry else None


@dataclasses.dataclass(frozen=True)
class ChatNotes:
    """The genuine trailers of a chat's stored user messages, oldest first."""

    trailers: tuple[Trailer, ...] = ()

    @classmethod
    def of(cls, user_contents: Iterable[str]) -> ChatNotes:
        found = (parse_trailer(content) for content in user_contents)
        return cls(tuple(t for t in found if t is not None))

    @property
    def has_notes(self) -> bool:
        return bool(self.trailers)

    def since_restart(self) -> Sequence[Trailer]:
        """The trailers of the current provider chain: from the last ``restart`` turn on (that
        turn's own items included), or all of them when there was none."""
        start = 0
        for index, trailer in enumerate(self.trailers):
            if trailer.restart:
                start = index
        return self.trailers[start:]

    def inherited_kinds(self) -> frozenset[str]:
        kinds: set[str] = set()
        for trailer in self.since_restart():
            kinds |= trailer.kinds
        return frozenset(kinds)

    def documents(self) -> int:
        return sum(t.documents for t in self.since_restart())

    def document_bytes(self) -> int:
        return sum(t.document_bytes for t in self.since_restart())

    def earlier_attachments(self) -> int:
        """Every attachment ever noted in the chat (what a replay does not resend)."""
        return sum(t.items for t in self.trailers)


MAX_CHAT_DOCUMENTS = 30
MAX_CHAT_DOCUMENT_BYTES = 50 * media.MIB


def check_chat_limits(notes: ChatNotes, new: Sequence[media.Attachment]) -> None:
    """Refuse a CHAINED send whose documents, with those counted from the stored notes since the
    last restart, would pass the API's limits (30 documents, 50 MiB of decoded document bytes; a
    URL document counts toward the 30 and adds no bytes). No request has been made yet."""
    docs = [item for item in new if item.kind == "document"]
    count = notes.documents() + len(docs)
    size = notes.document_bytes() + sum(item.size for item in docs if item.source != "url")
    if count > MAX_CHAT_DOCUMENTS:
        raise PerplexityError(
            "invalid_request",
            f"attachments: a chat holds at most {MAX_CHAT_DOCUMENTS} documents "
            f"({notes.documents()} already in this one, {len(docs)} more sent); start a new chat "
            "or send with replay true, which starts a new provider chain",
        )
    if size > MAX_CHAT_DOCUMENT_BYTES:
        raise PerplexityError(
            "invalid_request",
            f"attachments: a chat holds at most {MAX_CHAT_DOCUMENT_BYTES // media.MIB} MiB of "
            "documents; start a new chat or send with replay true, which starts a new provider "
            "chain",
        )

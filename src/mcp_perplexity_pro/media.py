"""Attachments: the grammar of an item, its kind and media type, byte signatures, URL rules,
limits and the request parts (spec ``media-attachments``).

Pure but for the local read, which is not here: a path item is parsed (``parse_attachments``),
read elsewhere (task 1.3) and its bytes put on the item before ``build_parts``. Nothing in this
module logs, and no error text repeats an attachment's contents (a ``data:`` item is shown as its
position and media type, a URL never with its credentials, query or fragment).

Do not use ``from __future__ import annotations`` where FastMCP reads annotations; this module
holds no tool, so it is not needed either way.
"""

import base64
import binascii
import dataclasses
import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple
from urllib.parse import unquote, urlsplit

from mcp_perplexity_pro.errors import PerplexityError

MAX_ATTACHMENTS = 10
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_INLINE_BYTES = 1024 * 1024
MAX_BODY_BYTES = 64 * 1024 * 1024
BODY_OVERHEAD = 4096  # a fixed allowance for the JSON around the parts
MAX_URL_CHARS = 2048
MAX_NAME_BYTES = 255
MAX_NOTE_NAME = 60
MAX_TRAILER = 1500

MIB = 1024 * 1024

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# media type -> (kind, file extension for a document filename)
SUPPORTED: dict[str, tuple[str, str]] = {
    "image/png": ("image", ".png"),
    "image/jpeg": ("image", ".jpg"),
    "image/webp": ("image", ".webp"),
    "image/gif": ("image", ".gif"),
    "application/pdf": ("document", ".pdf"),
    "application/msword": ("document", ".doc"),
    DOCX: ("document", ".docx"),
    "text/plain": ("document", ".txt"),
    "application/rtf": ("document", ".rtf"),
}
# a second spelling of one type, normalised on the way in
ALIASES = {"text/rtf": "application/rtf", "image/jpg": "image/jpeg"}

EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": DOCX,
    ".txt": "text/plain",
    ".rtf": "application/rtf",
}
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".wma"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mpeg", ".mpg"})

SUPPORTED_LIST = "png, jpeg, webp, gif (images); pdf, doc, docx, txt, rtf (documents)"

_PREFIX = re.compile(r"^([a-z]+/[a-z0-9.+-]+)::")
_DATA_URI = re.compile(r"^data:([^;,]*)((?:;[^;,]*)*),(.*)$", re.DOTALL | re.IGNORECASE)
_HOST = re.compile(r"[A-Za-z0-9._-]+")
_CONTROL = re.compile(r"[\x00-\x20\x7f]")


@dataclasses.dataclass(frozen=True)
class Attachment:
    """One checked attachment. ``data`` is the decoded inline bytes, or the file's bytes once a
    path item has been read; a URL item never has bytes. ``size`` is the decoded size (0 for a
    URL, set from the descriptor before a read for a path)."""

    index: int
    source: str  # "path" | "url" | "data"
    kind: str  # "image" | "document"
    media_type: str
    name: str  # a file's base name, or the document filename the API will see
    path: str | None = None
    url: str | None = None
    data: bytes | None = None
    size: int = 0
    written: str = ""  # a path item as the caller wrote it (for error text, cut when shown)


class Built(NamedTuple):
    parts: list[dict[str, Any]]
    notes: list[str]
    trailer: str


def label(index: int) -> str:
    return f"attachments[{index}]"


def _invalid(message: str) -> PerplexityError:
    return PerplexityError("invalid_request", message)


# --- the list ------------------------------------------------------------------------------


def parse_attachments(raw: object) -> list[Attachment]:
    """Check the whole list and return one ``Attachment`` per item; no file is read."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _invalid("attachments must be a list of strings")
    if len(raw) > MAX_ATTACHMENTS:
        raise _invalid(f"attachments: at most {MAX_ATTACHMENTS} attachments per call")
    for i, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise _invalid(f"{label(i)}: must be a non-blank string")
    return [parse_item(item, i) for i, item in enumerate(raw)]


def parse_item(raw: str, index: int) -> Attachment:
    """One item: prefix removed first, then classified case-insensitively on its scheme."""
    prefix: str | None = None
    match = _PREFIX.match(raw)
    if match:
        prefix = ALIASES.get(match.group(1), match.group(1))
        raw = raw[match.end() :]
    scheme = raw[:8].lower()
    if scheme.startswith("data:"):
        return _parse_data(raw, index, prefix)
    if scheme.startswith(("https://", "http://")):
        return _parse_url(raw, index, prefix)
    return _parse_path(raw, index, prefix)


def _type_from_extension(ext: str, where: str) -> str:
    ext = ext.lower()
    if ext in EXTENSIONS:
        return EXTENSIONS[ext]
    if ext in AUDIO_EXTENSIONS:
        raise _invalid(f"{where}: audio is not supported (the API accepts neither audio nor video)")
    if ext in VIDEO_EXTENSIONS:
        raise _invalid(f"{where}: video is not supported (the API accepts neither audio nor video)")
    shown = ext if ext and len(ext) <= 12 else "(none)"
    raise _invalid(f"{where}: type {shown} is not supported; supported: {SUPPORTED_LIST}")


def _checked_type(media_type: str, where: str) -> str:
    media_type = ALIASES.get(media_type.lower(), media_type.lower())
    if media_type in SUPPORTED:
        return media_type
    if media_type.startswith("audio/"):
        raise _invalid(f"{where}: audio is not supported (the API accepts neither audio nor video)")
    if media_type.startswith("video/"):
        raise _invalid(f"{where}: video is not supported (the API accepts neither audio nor video)")
    shown = media_type if re.fullmatch(r"[a-z0-9.+/-]{1,60}", media_type) else "(unreadable)"
    raise _invalid(f"{where}: type {shown} is not supported; supported: {SUPPORTED_LIST}")


def _document_name(base: str, media_type: str) -> str:
    """The base name when it fits and carries the type's extension, else ``document`` + it."""
    ext = SUPPORTED[media_type][1]
    stem, dot, suffix = base.rpartition(".")
    plain = (
        bool(base)
        and not _CONTROL.search(base)
        and "/" not in base
        and len(base.encode()) <= MAX_NAME_BYTES
    )
    if plain and dot and stem and f".{suffix.lower()}" == ext:
        return f"{stem}.{suffix.lower()}"
    return f"document{ext}"


# --- a local path --------------------------------------------------------------------------


def _parse_path(raw: str, index: int, prefix: str | None) -> Attachment:
    where = label(index)
    if "\x00" in raw:
        raise _invalid(f"{where}: the path holds a NUL byte")
    if raw.startswith("~/"):
        path = str(Path.home() / raw[2:])
    elif raw.startswith("/"):
        path = raw
    else:
        raise _invalid(f"{where}: a path must be absolute or start with ~/")
    media_type = _type_from_extension(PurePosixPath(path).suffix, where)
    if prefix is not None and prefix != media_type:
        raise _invalid(f"{where}: the prefix {prefix} disagrees with the type {media_type}")
    kind = SUPPORTED[media_type][0]
    base = PurePosixPath(path).name
    name = _document_name(base, media_type) if kind == "document" else base
    return Attachment(index, "path", kind, media_type, name, path=path, written=raw)


# --- inline data ---------------------------------------------------------------------------


def _parse_data(raw: str, index: int, prefix: str | None) -> Attachment:
    where = label(index)
    match = _DATA_URI.match(raw)
    if not match:
        raise _invalid(f"{where}: inline data must look like data:<type>;base64,<data>")
    media_type = _checked_type(match.group(1), where)
    params = [p.lower() for p in match.group(2).split(";") if p]
    if "base64" not in params:
        raise _invalid(f"{where}: inline data must be base64 ({media_type}): add ;base64")
    if prefix is not None and prefix != media_type:
        raise _invalid(f"{where}: the prefix {prefix} disagrees with the type {media_type}")
    payload = match.group(3)
    # the decoded size is known from the length, so an oversized string is refused before any
    # decoding (and a hostile one is never decoded)
    padding = payload.count("=", max(0, len(payload) - 2))
    estimate = max(0, len(payload) * 3 // 4 - padding)
    if estimate > MAX_INLINE_BYTES:
        raise _invalid(
            f"{where}: inline data is over {MAX_INLINE_BYTES // MIB} MiB ({media_type}); "
            "attach a path or a URL instead"
        )
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise _invalid(f"{where}: the inline data is not valid base64 ({media_type})") from None
    if len(data) > MAX_INLINE_BYTES:
        raise _invalid(
            f"{where}: inline data is over {MAX_INLINE_BYTES // MIB} MiB ({media_type}); "
            "attach a path or a URL instead"
        )
    if not check_bytes(media_type, data):
        raise _invalid(f"{where}: the bytes are not a {media_type}")
    kind, ext = SUPPORTED[media_type]
    name = f"document{ext}" if kind == "document" else f"inline{ext}"
    return Attachment(index, "data", kind, media_type, name, data=data, size=len(data))


# --- a URL ---------------------------------------------------------------------------------


def _parse_url(raw: str, index: int, prefix: str | None) -> Attachment:
    where = label(index)
    if raw[:8].lower() != "https://":
        raise _invalid(f"{where}: the API needs an HTTPS URL, not http")
    if len(raw) > MAX_URL_CHARS:
        raise _invalid(f"{where}: a URL is at most {MAX_URL_CHARS} characters")
    if "\\" in raw or _CONTROL.search(raw):
        raise _invalid(f"{where}: the URL holds a space, backslash or control character")
    if "#" in raw:
        raise _invalid(f"{where}: the URL holds a fragment")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise _invalid(f"{where}: the URL is malformed") from None
    netloc = parts.netloc
    if "@" in netloc:
        raise _invalid(f"{where}: the URL carries credentials")
    host = parts.hostname or ""
    if "[" in netloc:
        raise _invalid(f"{where}: an IPv6 literal is not accepted")
    if not host:
        raise _invalid(f"{where}: the URL has no host")
    if not _HOST.fullmatch(host):
        if not host.isascii():
            raise _invalid(f"{where}: use the punycode form of an internationalized host")
        raise _invalid(f"{where}: the URL host holds characters a host name cannot")
    if port not in (None, 443):
        raise _invalid(f"{where}: only port 443 is accepted")
    path = unquote(parts.path)
    if prefix is not None:
        media_type = _checked_type(prefix, where)
    else:
        suffix = PurePosixPath(path).suffix.lower()
        if suffix in EXTENSIONS or suffix in AUDIO_EXTENSIONS or suffix in VIDEO_EXTENSIONS:
            media_type = _type_from_extension(suffix, where)
        else:
            raise _invalid(
                f"{where}: the type cannot be derived from the URL; name it with a prefix, "
                "for example application/pdf::https://example.com/download"
            )
    kind = SUPPORTED[media_type][0]
    name = ""
    if kind == "document":
        name = _document_name(PurePosixPath(path).name, media_type)
    return Attachment(index, "url", kind, media_type, name, url=raw)


# --- bytes ---------------------------------------------------------------------------------


def check_bytes(media_type: str, data: bytes) -> bool:
    """Whether the leading bytes (the whole text for TXT) match the media type."""
    if media_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if media_type == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if media_type == "image/gif":
        return data[:6] in (b"GIF87a", b"GIF89a")
    if media_type == "application/pdf":
        return data.startswith(b"%PDF-")
    if media_type == "application/msword":
        return data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if media_type == DOCX:
        return data.startswith(b"PK\x03\x04")
    if media_type == "application/rtf":
        return data.startswith(b"{\\rtf")
    if media_type == "text/plain":
        if b"\x00" in data:
            return False
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    return False


def verify_file_bytes(item: Attachment, data: bytes) -> None:
    """The check a path item takes after its read: the bytes must match its extension's type."""
    if not check_bytes(item.media_type, data):
        raise _invalid(f"{label(item.index)}: the file's bytes are not a {item.media_type}")


# --- limits --------------------------------------------------------------------------------


def check_sizes(items: Sequence[Attachment]) -> None:
    """Per file and per call, in decoded bytes (URLs count 0)."""
    total = 0
    for item in items:
        if item.size > MAX_FILE_BYTES:
            raise _invalid(
                f"{label(item.index)}: a file is at most {MAX_FILE_BYTES // MIB} MiB "
                f"({item.media_type})"
            )
        total += item.size
    if total > MAX_TOTAL_BYTES:
        raise _invalid(f"attachments: at most {MAX_TOTAL_BYTES // MIB} MiB in total per call")


def body_size(items: Sequence[Attachment], text: str) -> int:
    """The request body size, computed (4 x ceil(n / 3) per item) before any base64 is built."""
    encoded = sum(4 * math.ceil(item.size / 3) for item in items if item.source != "url")
    urls = sum(len(item.url or "") for item in items if item.source == "url")
    return encoded + urls + len(text.encode()) + BODY_OVERHEAD


def check_body_size(items: Sequence[Attachment], text: str) -> None:
    if body_size(items, text) > MAX_BODY_BYTES:
        raise _invalid(f"attachments: the request body would be over {MAX_BODY_BYTES // MIB} MiB")


# --- parts and notes -----------------------------------------------------------------------


def _sha12(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _clean_name(name: str) -> str:
    out = []
    for ch in name[:MAX_NOTE_NAME]:
        bad = ch in ";()[]" or unicodedata.category(ch).startswith("C")
        out.append("_" if bad else ch)
    return "".join(out)


def note_item(item: Attachment) -> str:
    """One item of the trailer: never a path, query or URL path, never bytes."""
    if item.source == "url":
        parts = urlsplit(item.url or "")
        host = (parts.hostname or "").lower()
        digest = _sha12((host + unquote(parts.path)).encode())
        return f"{host} ({item.media_type}, url sha256 {digest})"
    data = item.data if item.data is not None else b""
    name = _clean_name(item.name)
    return f"{name} ({item.media_type}, {len(data)} bytes, sha256 {_sha12(data)})"


def render_trailer(items: Sequence[Attachment], notes: Sequence[str]) -> str:
    """``[attachments: a; b]``, or at 1500 characters a prefix of the items plus a count of the
    hidden ones (``+N more: <d> documents, <i> images, <b> bytes``)."""
    full = "[attachments: " + "; ".join(notes) + "]"
    if len(full) <= MAX_TRAILER:
        return full
    shown: list[str] = []
    budget = MAX_TRAILER - len("[attachments: ") - len("]") - 80  # room for the tail
    used = 0
    for note in notes:
        add = len(note) + (2 if shown else 0)
        if used + add > budget:
            break
        shown.append(note)
        used += add
    hidden = items[len(shown) :]
    docs = sum(1 for i in hidden if i.kind == "document")
    imgs = len(hidden) - docs
    size = sum(i.size for i in hidden)
    tail = f"+{len(hidden)} more: {docs} documents, {imgs} images, {size} bytes"
    return "[attachments: " + "; ".join([*shown, tail]) + "]"


def build_parts(items: Sequence[Attachment]) -> Built:
    """The request parts after the text part, in the order given, with the stored notes."""
    parts: list[dict[str, Any]] = []
    for item in items:
        if item.source != "url" and item.data is None:
            raise ValueError(f"{label(item.index)}: the file has not been read")
        if item.kind == "image":
            value = item.url
            if value is None:
                value = f"data:{item.media_type};base64,{_b64(item.data)}"
            parts.append({"type": "input_image", "image_url": value})
        elif item.source == "url":
            parts.append({"type": "input_file", "file_url": item.url, "filename": item.name})
        else:
            parts.append(
                {"type": "input_file", "filename": item.name, "file_data": _b64(item.data)}
            )
    notes = [note_item(i) for i in items]
    return Built(parts, notes, render_trailer(items, notes))


def _b64(data: bytes | None) -> str:
    return base64.b64encode(data or b"").decode()


# --- validation error text -----------------------------------------------------------------

_INPUT_VALUE = re.compile(r"input_value=.*(?=, input_type=)")


def drop_attachment_input_values(text: str) -> str:
    """Remove ``input_value=...`` from the lines of a pydantic validation text that belong to an
    ``attachments`` error, so a rejected value (a path, a URL, inline bytes) is never quoted.
    The remaining text still goes through ``redact_text``."""
    out: list[str] = []
    current = ""
    for line in text.split("\n"):
        if line and not line[0].isspace():
            current = line
        if current.startswith("attachments"):
            line = _INPUT_VALUE.sub("input_value=[dropped]", line)
        out.append(line)
    return "\n".join(out)

"""The local read of attachments: a path is opened safely, its real path checked, its bytes read
within a process-wide budget (spec ``media-attachments``, design D4 and D5).

Everything blocking runs in ``asyncio.to_thread``. The order is fixed: the HTTP default is
checked before any file is opened; each path is opened (``O_NOFOLLOW``, ``O_NONBLOCK``), shown to
be a regular file by its descriptor and checked against the roots and the deny list by the
DESCRIPTOR's real path, never by the caller's string; sizes and the whole call's share of bytes
are known before a byte is read; the share is taken at once for the whole call; then the files
are read, one byte past the descriptor's size at most, and their bytes checked against their type.
Errors name the item and never hold file contents.
"""

import asyncio
import dataclasses
import errno
import fnmatch
import os
import stat
import sys
from collections import deque
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from mcp_perplexity_pro import media
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.media import Attachment, label

MAX_INFLIGHT_BYTES = 64 * 1024 * 1024
ACQUIRE_TIMEOUT = 30.0
SHOWN_PATH_CHARS = 200

DENY_DIRS = (".ssh", ".aws", ".gnupg", ".config", ".claude", ".kube")
DENY_NAMES = ("ecosystem*.cjs", ".env*")

_fstat = os.fstat  # an alias a test can replace to model a file that grows


@dataclasses.dataclass(frozen=True)
class AttachPolicy:
    """What a local path may be: ``roots`` (empty means any readable path), whether the transport
    is HTTP (paths are then refused without roots), the data directory (always denied) and the
    home directory the deny list hangs from."""

    roots: tuple[str, ...] = ()
    http: bool = False
    data_dir: Path | None = None
    home: Path | None = None


def _invalid(message: str) -> PerplexityError:
    return PerplexityError("invalid_request", message)


def _shown(item: Attachment) -> str:
    return (item.written or item.path or "")[:SHOWN_PATH_CHARS]


# --- the byte limiter ----------------------------------------------------------------------


class ByteLimiter:
    """A process-wide budget of decoded bytes in flight (asyncio's semaphore counts units, not
    bytes). A call's whole share is taken at once or not at all, in arrival order, so no call
    ever holds a partial share. ``release`` is synchronous, so a cancelled caller cannot leave
    bytes held."""

    def __init__(self, capacity: int = MAX_INFLIGHT_BYTES) -> None:
        self.capacity = capacity
        self.used = 0
        self._waiters: deque[tuple[int, asyncio.Future[None]]] = deque()

    async def acquire(self, share: int, timeout: float | None = None) -> None:
        if share > self.capacity:
            raise _invalid(
                f"attachments: this call needs {share // media.MIB} MiB of memory at once and the "
                f"server allows {self.capacity // media.MIB} MiB"
            )
        if share <= 0:
            return
        if not self._waiters and self.used + share <= self.capacity:
            self.used += share
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        entry = (share, future)
        self._waiters.append(entry)
        try:
            await asyncio.wait_for(future, ACQUIRE_TIMEOUT if timeout is None else timeout)
        except TimeoutError:
            self._abandon(entry)
            raise PerplexityError(
                "rate_limited",
                "attachments: waited for other calls to release attachment memory; this is a "
                "local wait, no Retry-After applies, try again shortly",
            ) from None
        except BaseException:
            self._abandon(entry)
            raise

    def _abandon(self, entry: tuple[int, asyncio.Future[None]]) -> None:
        share, future = entry
        if future.done() and not future.cancelled():
            self.used -= share  # granted just before the wait gave up: hand it back
        elif entry in self._waiters:
            self._waiters.remove(entry)
        self._grant()

    def release(self, share: int) -> None:
        if share <= 0:
            return
        self.used -= share
        self._grant()

    def _grant(self) -> None:
        while self._waiters:
            share, future = self._waiters[0]
            if future.done():
                self._waiters.popleft()
                continue
            if self.used + share > self.capacity:
                return
            self._waiters.popleft()
            self.used += share
            future.set_result(None)


# --- the real path -------------------------------------------------------------------------


def _real_path_of_fd(fd: int) -> str:
    """The descriptor's real path: ``F_GETPATH`` on macOS, ``/proc/self/fd`` on Linux; anything
    else fails closed."""
    import fcntl

    if sys.platform == "darwin" and hasattr(fcntl, "F_GETPATH"):
        raw = fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024)
        return os.fsdecode(raw.split(b"\0", 1)[0])
    if sys.platform.startswith("linux"):
        return os.readlink(f"/proc/self/fd/{fd}")
    raise OSError("no way to read a descriptor's path on this platform")


def _case_insensitive(directory: str) -> bool:
    """Whether ``directory`` is on a case-insensitive volume (detected, never assumed)."""
    swapped = directory.swapcase()
    if swapped == directory:
        return False
    try:
        return os.path.samefile(directory, swapped)
    except OSError:
        return False


def _inside(real: Path, base: Path) -> bool:
    if _case_insensitive(str(base)):
        return Path(str(real).casefold()).is_relative_to(Path(str(base).casefold()))
    return real.is_relative_to(base)


def _resolved(path: str | Path) -> Path:
    return Path(os.path.realpath(path))


def _deny_dirs(policy: AttachPolicy) -> list[Path]:
    home = policy.home if policy.home is not None else Path.home()
    dirs = [_resolved(home / name) for name in DENY_DIRS]
    if policy.data_dir is not None:
        dirs.append(_resolved(policy.data_dir))
    return dirs


def check_real_path(real: str, policy: AttachPolicy, where: str) -> None:
    """The deny list (always) and the roots (when set), applied to the opened file's real path."""
    path = Path(real)
    if any(fnmatch.fnmatchcase(path.name.lower(), pattern) for pattern in DENY_NAMES):
        raise _invalid(f"{where}: the file name is denied (credentials and environment files)")
    if any(_inside(path, deny) for deny in _deny_dirs(policy)):
        raise _invalid(f"{where}: the path is denied (it is inside a protected directory)")
    if policy.roots and not any(_inside(path, _resolved(root)) for root in policy.roots):
        raise _invalid(
            f"{where}: the path is outside the allowed directories (PERPLEXITY_ATTACH_ROOTS)"
        )


def _open_checked(item: Attachment, policy: AttachPolicy) -> tuple[int, int]:
    """Open one path item and return ``(descriptor, size)``; nothing has been read."""
    where = label(item.index)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(item.path or "", flags)
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            raise PerplexityError("not_found", f"{where}: no such file: {_shown(item)}") from None
        if exc.errno == errno.ELOOP:
            raise _invalid(f"{where}: symbolic links are not followed: {_shown(item)}") from None
        if exc.errno in (errno.EACCES, errno.EPERM):
            raise _invalid(f"{where}: permission denied: {_shown(item)}") from None
        if exc.errno == errno.ENAMETOOLONG:
            raise _invalid(f"{where}: the path is too long") from None
        raise _invalid(
            f"{where}: the file cannot be opened ({os.strerror(exc.errno or 0)})"
        ) from None
    try:
        info = _fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _invalid(
                f"{where}: not a regular file (a directory, pipe or device): {_shown(item)}"
            )
        try:
            real = _real_path_of_fd(fd)
        except OSError:
            raise _invalid(f"{where}: the file's real path cannot be determined") from None
        check_real_path(real, policy, where)
        if info.st_size > media.MAX_FILE_BYTES:
            raise _invalid(
                f"{where}: a file is at most {media.MAX_FILE_BYTES // media.MIB} MiB "
                f"({item.media_type})"
            )
        return fd, info.st_size
    except BaseException:
        os.close(fd)
        raise


def _read_bounded(fd: int, size: int, where: str) -> bytes:
    """Read the file, stopping one byte past its descriptor size: a file that grew fails."""
    limit = size + 1
    chunks: list[bytes] = []
    got = 0
    while got < limit:
        chunk = os.read(fd, min(1024 * 1024, limit - got))
        if not chunk:
            break
        chunks.append(chunk)
        got += len(chunk)
    if got > size:
        raise _invalid(f"{where}: the file grew while it was read (size limit)")
    return b"".join(chunks)


# --- the whole call ------------------------------------------------------------------------


@asynccontextmanager
async def hold_attachments(
    items: Sequence[Attachment],
    policy: AttachPolicy,
    limiter: ByteLimiter,
    *,
    text: str = "",
) -> AsyncIterator[list[Attachment]]:
    """Read every path item and yield all items with their bytes, holding the call's share of the
    process-wide budget until the block exits (success, failure or cancellation)."""
    paths = [i for i in items if i.source == "path"]
    if paths and policy.http and not policy.roots:
        raise _invalid(
            f"{label(paths[0].index)}: local paths are disabled over HTTP; set "
            "PERPLEXITY_ATTACH_ROOTS to a colon-separated list of absolute directories to "
            "enable them (a URL or inline data works without it)"
        )
    opened: dict[int, tuple[int, int]] = {}
    held = 0
    try:
        for item in paths:
            opened[item.index] = await asyncio.to_thread(_open_checked, item, policy)
        sized = [
            dataclasses.replace(i, size=opened[i.index][1]) if i.source == "path" else i
            for i in items
        ]
        media.check_sizes(sized)
        media.check_body_size(sized, text)
        share = sum(i.size for i in sized)
        await limiter.acquire(share)
        held = share
        loaded: list[Attachment] = []
        for item in sized:
            if item.source == "path":
                fd, size = opened[item.index]
                data = await asyncio.to_thread(_read_bounded, fd, size, label(item.index))
                media.verify_file_bytes(item, data)
                item = dataclasses.replace(item, data=data, size=len(data))
            loaded.append(item)
        yield loaded
    finally:
        for fd, _size in opened.values():
            try:
                os.close(fd)
            except OSError:
                pass
        limiter.release(held)


def http_paths_notice(roots: Sequence[str]) -> str | None:
    """The one startup line an HTTP server logs when local paths are disabled, else ``None``."""
    if roots:
        return None
    return (
        "local attachment paths are disabled over HTTP (PERPLEXITY_ATTACH_ROOTS is not set); "
        "URLs and inline data still work"
    )

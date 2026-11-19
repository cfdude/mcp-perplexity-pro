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
import threading
from collections import deque
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from mcp_perplexity_pro import media
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.media import Attachment, label
from mcp_perplexity_pro.settings import Settings

MAX_INFLIGHT_BYTES = 64 * 1024 * 1024
ACQUIRE_TIMEOUT = 30.0
SHOWN_PATH_CHARS = 200

DENY_DIRS = (".ssh", ".aws", ".gnupg", ".config", ".claude", ".kube", ".docker")
DENY_NAMES = (
    "ecosystem*.cjs",
    ".env",
    ".env.*",
    ".envrc",
    "*.env",
    "*.env.*",
    ".netrc",
    ".npmrc",
    ".pypirc",
)

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


@dataclasses.dataclass
class AttachState:
    """What the server holds for attachments: the process-wide byte limiter and whether the
    transport is HTTP (set by ``__main__.run``; a stdio server and a one-shot command read local
    paths, an HTTP one only inside ``PERPLEXITY_ATTACH_ROOTS``). One mutable holder on the app
    context, no globals."""

    limiter: ByteLimiter = dataclasses.field(default_factory=lambda: ByteLimiter())
    http: bool = False

    def policy(self, settings: Settings) -> AttachPolicy:
        return AttachPolicy(
            roots=settings.attach_root_dirs, http=self.http, data_dir=settings.data_dir
        )


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


UNIFORM_REFUSAL = "the path is not readable or not allowed"


def _not_allowed(where: str) -> PerplexityError:
    """The one refusal a restricted server gives for a path that is denied or outside the roots,
    whether or not it exists, so the text never says which (design D5)."""
    return _invalid(f"{where}: {UNIFORM_REFUSAL}")


def _name_denied(name: str) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in DENY_NAMES)


def check_real_path(real: str, policy: AttachPolicy, where: str) -> None:
    """The deny list (always) and the roots (when set), applied to a real path. When roots
    restrict, every refusal is the one uniform message."""
    path = Path(real)
    if _name_denied(path.name):
        if policy.roots:
            raise _not_allowed(where)
        raise _invalid(f"{where}: the file name is denied (credentials and environment files)")
    if any(_inside(path, deny) for deny in _deny_dirs(policy)):
        if policy.roots:
            raise _not_allowed(where)
        raise _invalid(f"{where}: the path is denied (it is inside a protected directory)")
    if policy.roots and not any(_inside(path, _resolved(root)) for root in policy.roots):
        raise _not_allowed(where)


def precheck_path(item: Attachment, policy: AttachPolicy) -> None:
    """The check that runs BEFORE any open: the caller's string, its parent directory resolved
    lexically (no file is touched), against the deny list and the roots. Without it the open's own
    error (no such file, permission denied) would tell an HTTP caller which paths exist outside
    the roots. The check on the opened descriptor's real path stays as the defence against a
    path that changes between the two."""
    where = label(item.index)
    path = Path(item.path or "")
    if _name_denied(path.name):
        check_real_path(str(path), policy, where)
    parent = _resolved(path.parent)
    if any(_inside(parent, deny) for deny in _deny_dirs(policy)):
        check_real_path(str(parent / path.name), policy, where)
    if policy.roots and not any(_inside(parent, _resolved(root)) for root in policy.roots):
        raise _not_allowed(where)


class FdSet:
    """The descriptors one call has opened, closed exactly once whatever happens to the caller.

    A thread that finishes an open after its caller was cancelled still returns a descriptor
    nothing would close, and a close while a thread still reads would hit a reused number. So a
    descriptor is registered here by the thread itself, under a lock: after ``close_all`` a late
    registration is refused and its thread closes the descriptor, and a descriptor being read is
    closed by its reader when done."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fds: dict[int, int] = {}
        self._busy: set[int] = set()
        self._closed = False

    def add(self, index: int, fd: int) -> bool:
        """Register an opened descriptor; ``False`` (the caller closes it) when the call is over.
        Unreachable through ``hold_attachments``, which waits for its threads before ``close_all``;
        kept so a caller that does not wait still cannot leak a descriptor."""
        with self._lock:
            if self._closed:
                return False
            self._fds[index] = fd
            return True

    def begin_read(self, index: int) -> int | None:
        with self._lock:
            if self._closed or index not in self._fds:
                return None
            self._busy.add(index)
            return self._fds[index]

    def end_read(self, index: int) -> None:
        with self._lock:
            self._busy.discard(index)
            if self._closed and index in self._fds:
                _close_quietly(self._fds.pop(index))

    def close_all(self) -> None:
        with self._lock:
            self._closed = True
            for index in list(self._fds):
                if index not in self._busy:
                    _close_quietly(self._fds.pop(index))

    def count(self) -> int:
        with self._lock:
            return len(self._fds)


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _open_checked(item: Attachment, policy: AttachPolicy, fds: FdSet) -> int:
    """Open one path item, register its descriptor in ``fds`` and return its size; nothing has
    been read. A call that is already over closes the descriptor instead."""
    where = label(item.index)
    precheck_path(item, policy)
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
        if not fds.add(item.index, fd):
            raise asyncio.CancelledError
        return info.st_size
    except BaseException:
        _close_quietly(fd)
        raise


def _read_bounded(fds: FdSet, index: int, size: int, where: str) -> bytes:
    """Read the file, stopping one byte past its descriptor size: a file that grew fails."""
    fd = fds.begin_read(index)
    if fd is None:
        raise asyncio.CancelledError
    try:
        return _read_fd(fd, size, where)
    finally:
        fds.end_read(index)


def _read_fd(fd: int, size: int, where: str) -> bytes:
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
    fds = FdSet()
    sizes: dict[int, int] = {}
    threads: list[asyncio.Future[object]] = []
    held = 0

    async def in_thread(fn, *args):
        future = asyncio.ensure_future(asyncio.to_thread(fn, *args))
        threads.append(future)
        return await asyncio.shield(future)

    try:
        for item in paths:
            sizes[item.index] = await in_thread(_open_checked, item, policy, fds)
        sized = [
            dataclasses.replace(i, size=sizes[i.index]) if i.source == "path" else i for i in items
        ]
        media.check_sizes(sized)
        media.check_body_size(sized, text)
        share = sum(i.size for i in sized)
        await limiter.acquire(share)
        held = share
        loaded: list[Attachment] = []
        for item in sized:
            if item.source == "path":
                data = await in_thread(
                    _read_bounded, fds, item.index, sizes[item.index], label(item.index)
                )
                media.verify_file_bytes(item, data)
                item = dataclasses.replace(item, data=data, size=len(data))
            loaded.append(item)
        yield loaded
    finally:
        try:
            await _settle(threads)  # may re-raise a cancel that arrived while it waited
        finally:
            fds.close_all()  # always runs, whatever _settle raised
            limiter.release(held)


async def _settle(threads: list[asyncio.Future[object]]) -> None:
    """Wait for every started thread, however often this task is cancelled meanwhile, so no
    thread still reads (or opens) when the descriptors close and the byte budget is handed
    back. A thread is bounded (one open, one read of at most 32 MiB). The cancel is re-raised."""
    cancelled = False
    while True:
        pending = [t for t in threads if not t.done()]
        if not pending:
            break
        try:
            await asyncio.shield(asyncio.gather(*pending, return_exceptions=True))
        except asyncio.CancelledError:
            cancelled = True
    for t in threads:
        if t.done() and not t.cancelled():
            t.exception()  # mark retrieved: a late open's error has no reader
    if cancelled:
        raise asyncio.CancelledError


def http_paths_notice(roots: Sequence[str]) -> str | None:
    """The one startup line an HTTP server logs when local paths are disabled, else ``None``."""
    if roots:
        return None
    return (
        "local attachment paths are disabled over HTTP (PERPLEXITY_ATTACH_ROOTS is not set); "
        "URLs and inline data still work"
    )

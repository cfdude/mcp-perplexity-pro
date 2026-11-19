"""media_read.py: the local read (media-attachments: a path is opened safely, its real path is
checked, the process-wide byte budget, size and error scenarios)."""

import asyncio
import logging
import os
import stat
from types import SimpleNamespace

import media_support as ms
import pytest

from mcp_perplexity_pro import media, media_read
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.media_read import AttachPolicy, ByteLimiter, hold_attachments
from mcp_perplexity_pro.settings import SettingsError, load_settings, parse_attach_roots

PNG = ms.png()
PDF = ms.pdf()


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


def policy(home, **kw):
    return AttachPolicy(home=home, data_dir=home / ".perplexity-pro", **kw)


def write(path, data=PNG):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


async def load(raw, pol, limiter=None, text=""):
    items = media.parse_attachments(raw)
    async with hold_attachments(items, pol, limiter or ByteLimiter(), text=text) as got:
        return got


async def refused(raw, pol, *needles, category="invalid_request", limiter=None):
    with pytest.raises(PerplexityError) as info:
        await load(raw, pol, limiter)
    assert info.value.category == category, str(info.value)
    for needle in needles:
        assert needle in str(info.value), str(info.value)
    return str(info.value)


# --- a safe open ---------------------------------------------------------------------------


async def test_a_png_path_is_read_and_checked(home):
    p = write(home / "shot.png")
    [item] = await load([p], policy(home))
    assert item.data == PNG and item.size == len(PNG)


async def test_a_tilde_path_reads_from_home(home):
    write(home / "shot.png")
    [item] = await load(["~/shot.png"], policy(home))
    assert item.data == PNG


async def test_missing_file_is_not_found_naming_the_path_as_written(home):
    text = await refused(
        [str(home / "missing.png")], policy(home), "attachments[0]", category="not_found"
    )
    assert str(home / "missing.png") in text


async def test_a_symlink_as_the_final_component_is_not_followed(home, tmp_path):
    target = write(tmp_path / "outside" / "real.png")
    link = home / "link.png"
    link.symlink_to(target)
    await refused([str(link)], policy(home), "symbolic links are not followed")


async def test_a_directory_and_a_fifo_fail_without_blocking(home):
    d = home / "dir.png"
    d.mkdir()
    await refused([str(d)], policy(home), "not a regular file")
    fifo = home / "pipe.txt"
    os.mkfifo(fifo)
    assert stat.S_ISFIFO(os.stat(fifo).st_mode)
    await asyncio.wait_for(refused([str(fifo)], policy(home), "not a regular file"), 5)


async def test_a_file_that_grows_fails_with_the_read_bounded(home, monkeypatch):
    p = write(home / "grow.pdf", PDF + b"x" * 1000)
    real = os.fstat

    def small(fd):
        info = real(fd)
        return SimpleNamespace(st_mode=info.st_mode, st_size=10)

    monkeypatch.setattr(media_read, "_fstat", small)
    reads = []
    real_read = os.read
    monkeypatch.setattr(os, "read", lambda fd, n: (reads.append(n), real_read(fd, n))[1])
    await refused([p], policy(home), "grew while it was read")
    assert sum(reads) <= 11  # one byte past the descriptor's size, never the whole file


async def test_os_errors_are_invalid_requests_naming_the_item(home):
    locked = write(home / "locked.png")
    os.chmod(locked, 0)
    try:
        await refused([locked], policy(home), "attachments[0]", "permission denied")
    finally:
        os.chmod(locked, 0o600)
    long = "/" + "a" * 5000 + ".png"
    await refused([long], policy(home), "attachments[0]")
    with pytest.raises(PerplexityError) as info:
        media.parse_attachments(["/a/b\x00.png"])
    assert info.value.category == "invalid_request" and "attachments[0]" in str(info.value)


async def test_bytes_that_do_not_match_the_extension_fail(home):
    p = write(home / "a.png", PDF)
    await refused([p], policy(home), "attachments[0]", "image/png")


async def test_no_message_holds_file_contents(home):
    secret = b"%PDF-1.4 TOPSECRETTOKEN"
    p = write(home / "a.png", secret)
    text = await refused([p], policy(home))
    assert "TOPSECRET" not in text


# --- the real path, the roots and the deny list --------------------------------------------


async def test_a_sibling_directory_with_a_common_prefix_is_outside_the_root(home):
    write(home / "work-secrets" / "a.txt", b"hello")
    (home / "work").mkdir()
    pol = policy(home, roots=(str(home / "work"),))
    await refused([str(home / "work-secrets" / "a.txt")], pol, "outside the allowed directories")


async def test_a_file_inside_the_root_is_accepted_and_one_outside_is_not(home):
    write(home / "work" / "a.png")
    write(home / "notes.png")
    pol = policy(home, roots=(str(home / "work"),))
    await load([str(home / "work" / "a.png")], pol)
    await refused([str(home / "notes.png")], pol, "outside the allowed directories")


async def test_a_symlinked_parent_that_leaves_the_root_is_refused(home, tmp_path):
    outside = tmp_path / "outside"
    write(outside / "a.png")
    (home / "work").mkdir()
    (home / "work" / "via").symlink_to(outside)
    pol = policy(home, roots=(str(home / "work"),))
    await refused([str(home / "work" / "via" / "a.png")], pol, "outside the allowed directories")


async def test_a_root_that_is_a_symlink_is_resolved_first(home, tmp_path):
    real = tmp_path / "real"
    write(real / "a.png")
    link = tmp_path / "link"
    link.symlink_to(real)
    await load([str(link / "a.png")], policy(home, roots=(str(link),)))


async def test_the_deny_list_beats_the_roots(home):
    write(home / ".ssh" / "notes.txt", b"hello")
    pol = policy(home, roots=(str(home),))
    await refused([str(home / ".ssh" / "notes.txt")], pol, "denied")
    write(home / ".claude" / "x.png")
    await refused([str(home / ".claude" / "x.png")], pol, "denied")


async def test_a_symlinked_deny_directory_denies_its_target(home, tmp_path):
    target = tmp_path / "elsewhere"
    write(target / "a.txt", b"hello")
    (home / ".ssh").symlink_to(target)
    await refused([str(target / "a.txt")], policy(home), "denied")


async def test_the_data_directory_is_denied(home):
    write(home / ".perplexity-pro" / "x.png")
    await refused([str(home / ".perplexity-pro" / "x.png")], policy(home), "denied")


@pytest.mark.parametrize("name", [".env.txt", ".env.local.png", "ecosystem.config.cjs"])
async def test_denied_base_names(home, name):
    # the type check comes first for a .cjs, so the name check is exercised on the real path
    path = home / "work" / name
    write(path, b"hello" if name.endswith(".txt") else PNG)
    suffix_ok = name.endswith((".txt", ".png"))
    if suffix_ok:
        await refused([str(path)], policy(home), "denied")
    else:
        await refused([str(path)], policy(home), "attachments[0]")
        with pytest.raises(PerplexityError, match="denied"):
            media_read.check_real_path(str(path), policy(home), "attachments[0]")


async def test_the_real_path_is_what_is_checked(home, monkeypatch):
    p = write(home / "a.png")
    monkeypatch.setattr(media_read, "_real_path_of_fd", lambda fd: str(home / ".ssh" / "a.png"))
    await refused([p], policy(home), "denied")


async def test_an_undeterminable_real_path_fails_closed(home, monkeypatch):
    p = write(home / "a.png")

    def boom(fd):
        raise OSError("nope")

    monkeypatch.setattr(media_read, "_real_path_of_fd", boom)
    await refused([p], policy(home), "real path cannot be determined")


async def test_case_insensitive_comparison_only_on_a_case_insensitive_volume(home, monkeypatch):
    p = write(home / "Work" / "a.png")
    insensitive = media_read._case_insensitive(str(home))
    pol = policy(home, roots=(str(home / "work"),))
    if insensitive:
        await load([p], pol)
    else:
        await refused([p], pol, "outside the allowed directories")


# --- HTTP and stdio ------------------------------------------------------------------------


async def test_http_without_roots_refuses_paths_before_opening_anything(home, monkeypatch):
    p = write(home / "a.png")
    opened = []
    real = os.open
    monkeypatch.setattr(os, "open", lambda *a, **k: (opened.append(a), real(*a, **k))[1])
    await refused([p], policy(home, http=True), "PERPLEXITY_ATTACH_ROOTS")
    assert not opened


async def test_http_with_roots_allows_a_path_inside_and_urls_always(home):
    write(home / "work" / "a.png")
    pol = policy(home, http=True, roots=(str(home / "work"),))
    await load([str(home / "work" / "a.png")], pol)
    got = await load(["https://example.com/a.png"], policy(home, http=True))
    assert got[0].url == "https://example.com/a.png"


async def test_stdio_without_roots_reads_any_readable_path(home):
    p = write(home / "a.png")
    await load([p], policy(home, http=False))


def test_the_http_startup_notice():
    assert "PERPLEXITY_ATTACH_ROOTS" in media_read.http_paths_notice(())
    assert media_read.http_paths_notice(("/a",)) is None


# --- the roots setting ---------------------------------------------------------------------


def test_attach_roots_parse(monkeypatch, make_settings):
    assert parse_attach_roots("") == ()
    assert parse_attach_roots("/a:/b/c/") == ("/a", "/b/c")
    for bad in ("rel", "/a:rel", "/a::/b", ":"):
        with pytest.raises(ValueError):
            parse_attach_roots(bad)
    assert make_settings(attach_roots="/a:/b").attach_root_dirs == ("/a", "/b")


def test_a_bad_attach_roots_value_fails_startup_naming_the_variable(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
    monkeypatch.setenv("PERPLEXITY_ATTACH_ROOTS", "not-absolute")
    with pytest.raises(SettingsError, match="PERPLEXITY_ATTACH_ROOTS"):
        load_settings()


def test_a_bad_attach_roots_value_does_not_break_help_or_the_schema(monkeypatch):
    from mcp_perplexity_pro.command import schema_source, settings_for_help

    monkeypatch.setenv("PERPLEXITY_ATTACH_ROOTS", "not-absolute")
    settings, warning = settings_for_help()
    assert warning and settings.attach_roots == ""
    assert schema_source()


# --- the byte limiter ----------------------------------------------------------------------


async def test_two_calls_share_the_budget_and_the_third_waits():
    limiter = ByteLimiter(64)
    await limiter.acquire(32)
    await limiter.acquire(32)
    third = asyncio.create_task(limiter.acquire(32))
    await asyncio.sleep(0.05)
    assert not third.done()
    limiter.release(32)
    await asyncio.wait_for(third, 1)
    assert limiter.used == 64


async def test_a_wait_past_the_timeout_is_rate_limited_with_no_retry_after():
    limiter = ByteLimiter(40)
    await limiter.acquire(32)
    with pytest.raises(PerplexityError) as info:
        await limiter.acquire(32, timeout=0.05)
    assert info.value.category == "rate_limited"
    assert "local wait" in str(info.value) and "Retry-After" in str(info.value)
    assert limiter.used == 32  # the waiter held nothing


async def test_no_partial_share_when_two_calls_arrive_together():
    limiter = ByteLimiter(40)
    a = asyncio.create_task(limiter.acquire(32))
    b = asyncio.create_task(limiter.acquire(32, timeout=0.05))
    done, _ = await asyncio.wait({a, b}, timeout=1)
    assert a.done() and a.exception() is None
    assert isinstance(b.exception(), PerplexityError)
    assert limiter.used == 32


async def test_a_share_above_the_limit_fails_at_once():
    limiter = ByteLimiter(16 * media.MIB)
    with pytest.raises(PerplexityError) as info:
        await asyncio.wait_for(limiter.acquire(32 * media.MIB), 1)
    assert info.value.category == "invalid_request"


async def test_the_share_is_released_when_the_call_fails_after_reading(home):
    limiter = ByteLimiter(10 * media.MIB)
    good = write(home / "a.png")
    bad = write(home / "b.png", PDF)  # the second fails its signature after the first was read
    with pytest.raises(PerplexityError):
        await load([good, bad], policy(home), limiter)
    assert limiter.used == 0
    await load([good], policy(home), limiter)
    assert limiter.used == 0


async def test_the_share_is_held_until_the_block_exits(home):
    limiter = ByteLimiter(10 * media.MIB)
    p = write(home / "a.png")
    items = media.parse_attachments([p])
    async with hold_attachments(items, policy(home), limiter):
        assert limiter.used == len(PNG)
    assert limiter.used == 0


async def test_a_cancelled_waiter_leaves_nothing_held():
    limiter = ByteLimiter(40)
    await limiter.acquire(32)
    waiter = asyncio.create_task(limiter.acquire(32))
    await asyncio.sleep(0.02)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    limiter.release(32)
    assert limiter.used == 0
    await limiter.acquire(40)


# --- limits through the read ---------------------------------------------------------------


async def test_a_file_over_the_per_file_limit_is_refused_before_the_read(home, monkeypatch):
    monkeypatch.setattr(media, "MAX_FILE_BYTES", 100)
    p = write(home / "a.pdf", PDF)
    reads = []
    real_read = os.read
    monkeypatch.setattr(os, "read", lambda fd, n: (reads.append(n), real_read(fd, n))[1])
    await refused([p], policy(home), "attachments[0]", "MiB")
    assert not reads


async def test_the_total_limit_counts_every_file(home, monkeypatch):
    monkeypatch.setattr(media, "MAX_TOTAL_BYTES", len(PDF) + 10)
    a = write(home / "a.pdf", PDF)
    b = write(home / "b.pdf", PDF)
    await refused([a, b], policy(home), "attachments", "in total")


async def test_the_computed_body_backstop(home, monkeypatch):
    monkeypatch.setattr(media, "MAX_BODY_BYTES", 100)
    p = write(home / "a.png")
    await refused([p], policy(home), "request body")


async def test_nothing_is_logged_by_the_read(home, caplog):
    caplog.set_level(logging.DEBUG)
    p = write(home / "a.png")
    await load([p], policy(home))
    assert "base64" not in caplog.text and "iVBOR" not in caplog.text


async def test_the_http_runner_logs_the_notice_once_when_roots_are_unset(
    make_settings, monkeypatch, caplog
):
    from mcp_perplexity_pro import __main__ as entry

    class Quiet:
        async def serve(self):
            return None

    async def no_close(server):
        return None

    monkeypatch.setattr(entry, "build_http_server", lambda *a, **k: Quiet())
    monkeypatch.setattr(entry, "close_resources", no_close)
    caplog.set_level(logging.INFO)
    await entry._run_http(object(), make_settings(), 1.0)
    await entry._run_http(object(), make_settings(attach_roots="/a"), 1.0)
    notices = [r for r in caplog.records if "PERPLEXITY_ATTACH_ROOTS" in r.getMessage()]
    assert len(notices) == 1

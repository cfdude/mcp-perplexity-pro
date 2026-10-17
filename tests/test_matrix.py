"""model-matrix task 1.1: the pure matrix (``matrix.py``) and its packaged baseline.

Everything here is offline: the live list is the recorded fixture ``models_2026-10-17.json``,
and the two-process tests spawn plain interpreters on a temporary data directory.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fixture_support import FIXTURE_DIR

from mcp_perplexity_pro import matrix
from mcp_perplexity_pro.catalog import CatalogModel, Pricing, to_catalog_models
from mcp_perplexity_pro.models import ModelList

NOW = datetime(2026, 10, 18, 9, 30, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 18, 11, 0, 0, tzinfo=UTC)
STAMP = "2026-10-18T09:30:00Z"
LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"]

# The nine models of the 2026-10-17 effort probe that differ from "accepts every level".
REFUSE_XHIGH_AND_MAX = {
    "openai/gpt-5",
    "openai/gpt-5-mini",
    "openai/gpt-5-nano",
    "openai/gpt-5.1",
    "perplexity/kimi-k3",
}
REFUSE_MINIMAL = {"google/gemini-3.1-pro-preview"}
REFUSE_EVERYTHING = {
    "perplexity/deepseek-v4-pro-0813",
    "xai/grok-4.20-multi-agent",
    "xai/grok-4.20-reasoning",
}


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return json.loads((FIXTURE_DIR / "models_2026-10-17.json").read_text())


@pytest.fixture
def live(fixture_payload) -> list[CatalogModel]:
    return to_catalog_models(ModelList.model_validate(fixture_payload))


@pytest.fixture(scope="module")
def baseline() -> matrix.Matrix:
    return matrix.load_baseline()


@pytest.fixture
def data_dir(tmp_path) -> Path:
    return tmp_path


def path_of(data_dir: Path) -> Path:
    return data_dir / matrix.FILENAME


def new_model(model_id: str, **price) -> CatalogModel:
    return CatalogModel(
        id=model_id, provider=model_id.split("/")[0], pricing=Pricing(input=1.5, **price)
    )


def with_entry(m: matrix.Matrix, model_id: str) -> matrix.Matrix:
    copy = m.model_copy(deep=True)
    copy.models[model_id] = matrix.ModelEntry(
        provider="acme", status="available", pricing=matrix.Pricing(), first_seen=STAMP,
        last_seen=STAMP,
    )  # fmt: skip
    return copy


def python(code: str, *args: object, **kwargs) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-I", "-c", code, *map(str, args)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **kwargs,
    )


LOCK_HOLDER = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
print("locked", flush=True)
sys.stdin.readline()
"""

# A second server: takes the matrix lock through ``update`` and adds its own model inside it.
WRITER = """
import asyncio, sys
from pathlib import Path
from mcp_perplexity_pro import matrix

def add(m):
    print("inlock", flush=True)
    sys.stdin.readline()
    copy = m.model_copy(deep=True)
    copy.models[sys.argv[2]] = matrix.ModelEntry(
        provider="acme", status="available", pricing=matrix.Pricing(),
        first_seen="2026-10-18T09:30:00Z", last_seen="2026-10-18T09:30:00Z",
    )
    return copy

print(asyncio.run(matrix.update(Path(sys.argv[1]), add)).status, flush=True)
"""


class Holder:
    """A separate process holding ``model_matrix.lock`` until told to let go."""

    def __init__(self, data_dir: Path) -> None:
        self.proc = python(LOCK_HOLDER, data_dir / matrix.LOCK_FILENAME)
        assert self.proc.stdout.readline().strip() == "locked"

    def release(self) -> None:
        self.proc.stdin.write("\n")
        self.proc.stdin.flush()
        self.proc.wait(timeout=10)

    def __enter__(self) -> "Holder":
        return self

    def __exit__(self, *exc) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            stream.close()


# --- The matrix is one versioned file --------------------------------------------------------


async def test_a_refreshed_file_has_the_top_level_and_every_listed_model(data_dir, live, baseline):
    result = await matrix.update(
        data_dir, lambda m: matrix.merge(m, live, baseline, NOW).matrix, now=NOW
    )
    assert result.status == "written"
    doc = json.loads(path_of(data_dir).read_text())
    assert doc["version"] == 1 and doc["fetched_at"] == STAMP
    assert set(doc["models"]) == {m.id for m in live}
    nano = doc["models"]["openai/gpt-5-nano"]
    assert nano["pricing"] == {
        "input": 0.05,
        "output": 0.4,
        "cache_read": 0.005,
        "cache_write": None,
    }
    assert os.stat(path_of(data_dir)).st_mode & 0o777 == 0o600
    assert os.stat(data_dir / matrix.LOCK_FILENAME).st_mode & 0o777 == 0o600


def test_the_efforts_shape_round_trips(baseline):
    efforts = baseline.models["openai/gpt-5-nano"].efforts.model_dump()
    assert efforts["accepted"] == ["minimal", "low", "medium", "high"]
    assert efforts["refused"] == {"xhigh": 400, "max": 400}
    assert efforts["answers"] == {
        "control": 200, "minimal": 200, "low": 200, "medium": 200, "high": 200,
        "xhigh": 400, "max": 400,
    }  # fmt: skip
    assert efforts["source"] == "baseline" and efforts["probed_at"].endswith("Z")
    assert set(efforts) == {"accepted", "refused", "answers", "probed_at", "source"}


# --- The baseline: built from the recorded list and the effort probe -------------------------


def test_every_fixture_id_is_in_the_baseline_with_efforts_and_the_fixture_prices(
    fixture_payload, baseline
):
    entries = {m["id"]: m for m in fixture_payload["data"]}
    assert set(baseline.models) == set(entries)
    for model_id, raw in entries.items():
        row = baseline.models[model_id]
        assert row.status == "available" and row.probing_until is None
        assert row.provider == raw["owned_by"]
        assert row.efforts.source == "baseline" and row.efforts.probed_at
        assert set(row.efforts.answers) == {"control", *LEVELS}, model_id
        assert sorted(row.efforts.accepted + list(row.efforts.refused)) == sorted(LEVELS)
        prices = {
            k: raw["pricing"].get(k) for k in ("input", "output", "cache_read", "cache_write")
        }
        assert row.pricing.model_dump() == prices, model_id


def test_the_nine_differing_models_are_named_and_the_rest_accept_every_level(baseline):
    for model_id in REFUSE_XHIGH_AND_MAX:
        row = baseline.models[model_id].efforts
        assert row.accepted == LEVELS[:4] and row.refused == {"xhigh": 400, "max": 400}, model_id
    for model_id in REFUSE_MINIMAL:
        row = baseline.models[model_id].efforts
        assert row.accepted == LEVELS[1:] and row.refused == {"minimal": 400}, model_id
    for model_id in REFUSE_EVERYTHING:
        row = baseline.models[model_id].efforts
        assert row.accepted == [] and row.refused == dict.fromkeys(LEVELS, 400), model_id
        assert row.answers["control"] == 200, model_id
    nine = REFUSE_XHIGH_AND_MAX | REFUSE_MINIMAL | REFUSE_EVERYTHING
    assert len(nine) == 9
    for model_id, entry in baseline.models.items():
        if model_id not in nine:
            assert entry.efforts.accepted == LEVELS and entry.efforts.refused == {}, model_id


def test_the_baseline_is_read_with_importlib_resources_and_is_a_version_1_matrix():
    from importlib.resources import files

    raw = json.loads(
        files("mcp_perplexity_pro").joinpath("data/model_matrix_baseline.json").read_text()
    )
    assert raw["version"] == 1 and len(raw["models"]) == 54


# --- The matrix is never empty ---------------------------------------------------------------


def test_first_start_with_no_file_is_the_baseline(data_dir, baseline):
    loaded = matrix.load(path_of(data_dir), baseline)
    assert loaded.matrix == baseline and loaded.origin == "baseline" and loaded.state == "missing"
    assert not list(data_dir.iterdir())  # reading writes nothing


def test_a_missing_data_directory_is_not_created_by_a_read(tmp_path, baseline):
    loaded = matrix.load(tmp_path / "absent" / matrix.FILENAME, baseline)
    assert loaded.origin == "baseline" and not (tmp_path / "absent").exists()


@pytest.mark.parametrize(
    "content",
    ["this is not json", "", "   \n", "[1, 2]", '{"hello": 1}', '{"version": 1, "models": {}}'],
    ids=["text", "empty", "blank", "list", "not-a-matrix", "no-models"],
)
async def test_a_corrupt_file_gives_the_baseline_and_is_renamed_aside_by_the_first_write(
    data_dir, content, baseline, live
):
    path_of(data_dir).write_text(content)
    loaded = matrix.load(path_of(data_dir), baseline)
    assert loaded.matrix == baseline and loaded.origin == "baseline" and loaded.state == "corrupt"
    assert path_of(data_dir).read_text() == content  # a read never renames

    result = await matrix.update(
        data_dir, lambda m: matrix.merge(m, live, baseline, NOW).matrix, now=NOW, baseline=baseline
    )
    assert result.status == "written"
    (aside,) = data_dir.glob(f"{matrix.FILENAME}.corrupt-*")
    assert aside.read_text() == content  # moved, never deleted
    assert aside.name.endswith("20261018T093000Z")
    assert json.loads(path_of(data_dir).read_text())["version"] == 1


async def test_a_file_from_a_newer_version_is_left_untouched(data_dir, baseline, live, caplog):
    text = json.dumps({"version": 2, "fetched_at": STAMP, "models": {"x/y": {"anything": 1}}})
    path_of(data_dir).write_text(text)
    loaded = matrix.load(path_of(data_dir), baseline)
    assert loaded.matrix == baseline and loaded.origin == "baseline" and loaded.state == "newer"
    with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.matrix"):
        result = await matrix.update(
            data_dir, lambda m: matrix.merge(m, live, baseline, NOW).matrix, now=NOW
        )
    assert result.status == "newer_version"
    assert path_of(data_dir).read_text() == text
    assert not list(data_dir.glob("*.corrupt-*"))
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_a_stored_file_is_read_with_origin_file_and_not_modified(data_dir, baseline):
    stored = with_entry(baseline, "acme/stored")
    matrix.write(path_of(data_dir), stored)
    before = (path_of(data_dir).read_bytes(), os.stat(path_of(data_dir)).st_mtime_ns)
    loaded = matrix.load(path_of(data_dir), baseline)
    assert loaded.origin == "file" and loaded.state == "ok"
    assert "acme/stored" in loaded.matrix.models
    assert (path_of(data_dir).read_bytes(), os.stat(path_of(data_dir)).st_mtime_ns) == before


# --- Merging keeps what is known -------------------------------------------------------------


def test_a_new_model_is_added_available_unprobed_with_its_price_and_dates(baseline, live):
    merged = matrix.merge(baseline, [*live, new_model("acme/new-1", output=9.0)], baseline, NOW)
    assert merged.applied and merged.warning is None
    entry = merged.matrix.models["acme/new-1"]
    assert entry.provider == "acme" and entry.status == "available"
    assert entry.pricing.model_dump() == {
        "input": 1.5, "output": 9.0, "cache_read": None, "cache_write": None,
    }  # fmt: skip
    assert entry.first_seen == STAMP and entry.last_seen == STAMP and entry.probing_until is None
    assert entry.efforts.source == "unprobed" and entry.efforts.accepted == []
    assert entry.efforts.refused == {} and entry.efforts.answers == {}
    assert merged.matrix.fetched_at == STAMP and merged.matrix.version == 1


def test_a_model_the_baseline_knows_is_added_with_the_baseline_efforts(baseline, live):
    stored = baseline.model_copy(deep=True)
    del stored.models["openai/gpt-5-nano"]
    merged = matrix.merge(stored, live, baseline, NOW).matrix
    row = merged.models["openai/gpt-5-nano"]
    assert row.efforts == baseline.models["openai/gpt-5-nano"].efforts
    assert row.efforts.source == "baseline" and row.first_seen == STAMP


def test_a_listed_id_gets_the_new_price_and_last_seen_and_keeps_first_seen_and_efforts(
    baseline, live
):
    changed = [m.model_copy(deep=True) for m in live]
    changed[0].pricing.input = 123.0
    merged = matrix.merge(baseline, changed, baseline, LATER).matrix
    before, after = baseline.models[changed[0].id], merged.models[changed[0].id]
    assert after.pricing.input == 123.0
    assert after.last_seen == "2026-10-18T11:00:00Z" and after.first_seen == before.first_seen
    assert after.efforts == before.efforts


def test_a_vanished_model_is_removed_but_keeps_its_row_and_efforts(baseline, live):
    gone = live[7].id
    merged = matrix.merge(baseline, [m for m in live if m.id != gone], baseline, NOW)
    row = merged.matrix.models[gone]
    assert merged.applied and row.status == "removed"
    assert (
        row.efforts == baseline.models[gone].efforts
        and row.pricing == baseline.models[gone].pricing
    )
    assert row.last_seen == baseline.models[gone].last_seen  # not seen now, so not bumped


def test_a_reappearing_removed_model_is_available_again_with_its_efforts(baseline, live):
    gone = live[7].id
    removed = matrix.merge(baseline, [m for m in live if m.id != gone], baseline, NOW).matrix
    back = matrix.merge(removed, live, baseline, LATER).matrix.models[gone]
    assert back.status == "available" and back.last_seen == "2026-10-18T11:00:00Z"
    assert back.efforts == baseline.models[gone].efforts


def test_an_empty_list_changes_nothing_and_warns(baseline):
    merged = matrix.merge(baseline, [], baseline, NOW)
    assert not merged.applied and merged.matrix == baseline
    assert merged.warning and "empty" in merged.warning
    assert all(m.status == "available" for m in merged.matrix.models.values())


def test_a_truncated_list_changes_nothing_and_warns(baseline, live):
    merged = matrix.merge(baseline, live[:10], baseline, NOW)
    assert not merged.applied and merged.matrix == baseline
    assert merged.warning and "10" in merged.warning and "54" in merged.warning


def test_exactly_half_of_the_stored_ids_is_enough(baseline, live):
    merged = matrix.merge(baseline, live[:27], baseline, NOW)
    assert (
        merged.applied and sum(m.status == "removed" for m in merged.matrix.models.values()) == 27
    )


def test_an_overlap_of_a_big_unrelated_list_is_still_truncation(baseline, live):
    unrelated = [new_model(f"acme/m{i}") for i in range(200)]
    merged = matrix.merge(baseline, [*unrelated, *live[:5]], baseline, NOW)
    assert not merged.applied and merged.warning


def test_merge_never_mutates_its_input(baseline, live):
    snapshot = baseline.model_copy(deep=True)
    matrix.merge(baseline, [*live[:30], new_model("acme/new-1")], baseline, NOW)
    assert baseline == snapshot


# --- Writes are atomic -----------------------------------------------------------------------


def test_a_crash_before_the_replace_leaves_the_old_complete_file_and_no_temp_file(
    data_dir, baseline, monkeypatch
):
    old = with_entry(baseline, "acme/old")
    matrix.write(path_of(data_dir), old)
    before = path_of(data_dir).read_bytes()

    def crash(fd):
        raise OSError("disk went away")

    monkeypatch.setattr(matrix.os, "fsync", crash)
    with pytest.raises(OSError, match="disk went away"):
        matrix.write(path_of(data_dir), with_entry(baseline, "acme/new"))
    assert path_of(data_dir).read_bytes() == before
    assert not list(data_dir.glob("*.tmp"))


def test_write_makes_a_0600_file_in_the_data_directory_whatever_the_umask(data_dir, baseline):
    old_mask = os.umask(0)
    try:
        matrix.write(path_of(data_dir), baseline)
    finally:
        os.umask(old_mask)
    assert os.stat(path_of(data_dir)).st_mode & 0o777 == 0o600
    assert matrix.load(path_of(data_dir), baseline).matrix == baseline


async def test_a_cancelled_write_leaves_one_whole_file_and_frees_the_lock(
    data_dir, baseline, monkeypatch
):
    import threading

    old = with_entry(baseline, "acme/old")
    matrix.write(path_of(data_dir), old)
    started, proceed = threading.Event(), threading.Event()
    real_write = matrix.write

    def slow_write(path, value):
        started.set()
        assert proceed.wait(10)
        real_write(path, value)

    monkeypatch.setattr(matrix, "write", slow_write)
    task = asyncio.ensure_future(matrix.update(data_dir, lambda m: with_entry(m, "acme/new")))
    while not started.is_set():
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # the file is whole while the write is still in flight (the old one) ...
    assert "acme/old" in matrix.load(path_of(data_dir), baseline).matrix.models
    proceed.set()
    # ... and whole afterwards (the new one); the lock is released by the thread's finally
    lock = await matrix.acquire_lock(data_dir, timeout=5.0)
    lock.release()
    final = matrix.load(path_of(data_dir), baseline)
    assert final.state == "ok" and "acme/new" in final.matrix.models


# --- The lock is short and cancellable -------------------------------------------------------


async def test_two_writers_in_two_processes_lose_no_rows(data_dir, baseline):
    stored = with_entry(baseline, "acme/seed")
    matrix.write(path_of(data_dir), stored)
    first = python(WRITER, data_dir, "acme/from-first")
    try:
        assert first.stdout.readline().strip() == "inlock"  # it holds the lock now
        second = asyncio.ensure_future(
            matrix.update(data_dir, lambda m: with_entry(m, "acme/from-second"), timeout=10.0)
        )
        await asyncio.sleep(0.3)
        assert not second.done()  # waiting for the lock, not writing from a stale read
        first.stdin.write("\n")
        first.stdin.flush()
        assert (await second).status == "written"
        assert first.stdout.readline().strip() == "written"
    finally:
        first.kill() if first.poll() is None else None
        first.wait()
        for stream in (first.stdin, first.stdout, first.stderr):
            stream.close()
    models = matrix.load(path_of(data_dir), baseline).matrix.models
    assert {"acme/seed", "acme/from-first", "acme/from-second"} <= set(models)


async def test_a_lock_held_past_the_wait_skips_the_write_with_one_warning(
    data_dir, baseline, caplog
):
    stored = with_entry(baseline, "acme/seed")
    matrix.write(path_of(data_dir), stored)
    before = path_of(data_dir).read_bytes()
    with (
        Holder(data_dir) as holder,
        caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.matrix"),
    ):
        started = time.monotonic()
        result = await matrix.update(data_dir, lambda m: with_entry(m, "acme/never"), timeout=0.4)
        elapsed = time.monotonic() - started
        holder.release()
    assert result.status == "lock_timeout" and 0.35 <= elapsed < 3
    assert path_of(data_dir).read_bytes() == before
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


async def test_a_cancelled_wait_ends_at_once_never_holds_the_lock_and_writes_nothing(
    data_dir, baseline
):
    called = []

    def fn(m):
        called.append(1)
        return with_entry(m, "acme/never")

    with Holder(data_dir) as holder:
        task = asyncio.ensure_future(matrix.update(data_dir, fn, timeout=5.0))
        await asyncio.sleep(0.3)
        assert not task.done()
        started = time.monotonic()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert time.monotonic() - started < 0.5
        holder.release()
    assert not called and not path_of(data_dir).exists()
    lock = await matrix.acquire_lock(data_dir, timeout=1.0)  # nobody kept it
    lock.release()


async def test_the_wait_polls_in_the_event_loop_without_a_thread(data_dir, monkeypatch):
    threads = []
    real_to_thread = asyncio.to_thread

    async def spy(func, *args, **kwargs):
        threads.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(matrix.asyncio, "to_thread", spy)
    with Holder(data_dir) as holder:
        result = await matrix.update(data_dir, lambda m: m, timeout=0.3)
        holder.release()
    assert result.status == "lock_timeout" and threads == []  # the wait used no thread


async def test_a_leftover_temp_file_of_a_killed_writer_is_removed_by_the_next_writer(
    data_dir, baseline
):
    leftover = data_dir / "model_matrix.abc123.tmp"
    leftover.write_text("{half a mat")
    other = data_dir / "unrelated.tmp"
    other.write_text("keep")
    result = await matrix.update(data_dir, lambda m: with_entry(m, "acme/x"), now=NOW)
    assert result.status == "written"
    assert not leftover.exists() and other.exists()


async def test_a_function_that_returns_none_writes_nothing(data_dir):
    result = await matrix.update(data_dir, lambda m: None)
    assert result.status == "unchanged" and not path_of(data_dir).exists()


async def test_a_read_only_file_only_skips_the_write(data_dir, baseline, caplog):
    matrix.write(path_of(data_dir), with_entry(baseline, "acme/seed"))
    os.chmod(path_of(data_dir), 0o400)
    before = path_of(data_dir).read_bytes()
    try:
        with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.matrix"):
            result = await matrix.update(data_dir, lambda m: with_entry(m, "acme/never"))
    finally:
        os.chmod(path_of(data_dir), 0o600)
    assert result.status == "skipped"
    assert path_of(data_dir).read_bytes() == before and not list(data_dir.glob("*.tmp"))
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


async def test_a_read_only_directory_only_skips_the_write(data_dir, baseline, caplog):
    matrix.write(path_of(data_dir), with_entry(baseline, "acme/seed"))
    (data_dir / matrix.LOCK_FILENAME).touch(mode=0o600)
    before = path_of(data_dir).read_bytes()
    os.chmod(data_dir, 0o500)
    try:
        with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro.matrix"):
            result = await matrix.update(data_dir, lambda m: with_entry(m, "acme/never"))
    finally:
        os.chmod(data_dir, 0o700)
    assert result.status == "skipped" and path_of(data_dir).read_bytes() == before
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


# --- The module is pure ----------------------------------------------------------------------


def test_matrix_imports_no_httpx_sqlalchemy_or_fastmcp():
    code = (
        "import sys\n"
        "for name in ('fastmcp', 'sqlalchemy', 'httpx', 'httpx2', 'mcp'):\n"
        "    sys.modules[name] = None\n"  # a blocked import raises ImportError
        "import mcp_perplexity_pro.matrix\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

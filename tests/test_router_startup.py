"""PERPLEXITY_ROUTER_MARGIN, the evidence holder on the app context and the two startup warnings
(routing-v2 task 4.2; the routing-evidence lazy-loading and margin scenarios)."""

import json
import logging
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from evidence_support import document, figure
from server_support import server_env

from mcp_perplexity_pro import __main__ as entry
from mcp_perplexity_pro import routing_evidence as ev
from mcp_perplexity_pro.settings import Settings, SettingsError, load_settings

KEY = "test-dummy-api-key"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    import os

    for name in list(os.environ):
        if name.upper().startswith("PERPLEXITY_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PERPLEXITY_API_KEY", KEY)


def error_for(monkeypatch, **env):
    for name, value in env.items():
        monkeypatch.setenv(f"PERPLEXITY_{name}", value)
    with pytest.raises(SettingsError) as info:
        load_settings()
    return str(info.value)


# --- the margin setting -----------------------------------------------------------------------


def test_the_margin_defaults_to_3_in_dynamic_mode(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_ROUTING", "dynamic")
    s = load_settings()
    assert s.router_margin is None and s.router_margin_points == Decimal("3.0")
    assert s.ignored_routing_vars() == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", "0"), ("0.5", "0.5"), ("3", "3"), (" 7.25 ", "7.25"), ("20", "20"), ("2e1", "2E+1")],
)
def test_a_margin_from_0_to_20_is_accepted_exactly(monkeypatch, raw, expected):
    monkeypatch.setenv("PERPLEXITY_ROUTING", "dynamic")
    monkeypatch.setenv("PERPLEXITY_ROUTER_MARGIN", raw)
    s = load_settings()
    assert s.router_margin_points == Decimal(expected) and s.ignored_routing_vars() == []


@pytest.mark.parametrize("raw", ["25", "20.01", "-1", "-0.1", "abc", "", "nan", "inf", "1,5"])
def test_a_margin_outside_0_to_20_fails_dynamic_startup_naming_the_variable_and_range(
    monkeypatch, raw
):
    text = error_for(monkeypatch, ROUTING="dynamic", ROUTER_MARGIN=raw)
    assert "PERPLEXITY_ROUTER_MARGIN" in text and "0 to 20" in text and KEY not in text


@pytest.mark.parametrize("mode", ["standard", "custom"])
def test_outside_dynamic_the_margin_is_not_validated_and_is_reported_as_ignored(monkeypatch, mode):
    monkeypatch.setenv("PERPLEXITY_ROUTING", mode)
    if mode == "custom":
        for tier in ("LIGHT", "STANDARD", "COMPLEX"):
            monkeypatch.setenv(f"PERPLEXITY_TIER_{tier}", f"x/{tier.lower()}")
    monkeypatch.setenv("PERPLEXITY_ROUTER_MARGIN", "abc")
    s = load_settings()
    assert s.ignored_routing_vars() == ["PERPLEXITY_ROUTER_MARGIN"]
    assert s.router_margin_points == Decimal("3.0")  # never read outside dynamic


def test_the_default_margin_is_the_one_the_selector_names():
    from mcp_perplexity_pro import routing_select

    assert routing_select.MARGIN_POINTS == Decimal("3.0")
    assert Settings(api_key=KEY).router_margin_points == Decimal("3.0")


# --- the holder on the app context ------------------------------------------------------------


def test_building_the_server_reads_no_evidence_file_and_the_holder_is_on_the_context(
    make_settings, monkeypatch
):
    import httpx2

    from mcp_perplexity_pro.server import build_server

    def boom(*args, **kwargs):
        raise AssertionError("the evidence was read")

    monkeypatch.setattr(ev, "load", boom)
    monkeypatch.setattr(ev, "load_packaged", boom)
    settings = make_settings(routing="dynamic")
    server = build_server(settings, httpx2.AsyncClient(), engine=None)  # type: ignore[arg-type]
    assert isinstance(server.app.evidence, ev.EvidenceState)  # type: ignore[attr-defined]
    assert server.app.evidence.data_dir == settings.data_dir  # type: ignore[attr-defined]
    assert not settings.data_dir.exists()


def test_the_schema_builder_that_help_uses_reads_no_evidence(monkeypatch, tmp_path):
    from mcp_perplexity_pro.command import schema_source

    def boom(*args, **kwargs):
        raise AssertionError("the evidence was read")

    monkeypatch.setattr(ev, "load", boom)
    monkeypatch.setattr(ev, "load_packaged", boom)
    monkeypatch.setenv("PERPLEXITY_DATA_DIR", str(tmp_path / "data"))
    assert schema_source()
    assert not (tmp_path / "data").exists()


def test_perplexity_pro_help_touches_no_evidence_file_and_no_data_directory(tmp_path):
    env = server_env(tmp_path, PERPLEXITY_ROUTING="dynamic")
    done = subprocess.run(
        [sys.executable, "-m", "mcp_perplexity_pro.command", "help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert not (tmp_path / "data").exists() and "routing evidence" not in done.stderr


# --- the two startup warnings -----------------------------------------------------------------


@pytest.fixture
def restore_logging():
    root, fastmcp = logging.getLogger(), logging.getLogger("fastmcp")
    saved = (list(root.handlers), root.level, list(fastmcp.handlers), fastmcp.propagate)
    yield
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    fastmcp.handlers[:] = saved[2]
    fastmcp.propagate = saved[3]


def boot(make_settings, monkeypatch, *, serving=True, **settings):
    import httpx2

    from mcp_perplexity_pro import settings as settings_module

    cfg = make_settings(**settings)
    monkeypatch.setattr(settings_module, "load_settings", lambda: cfg)
    server, _ = entry.bootstrap(httpx2.AsyncClient(), serving=serving)
    return cfg, server


async def close(server):
    await server.app.http.aclose()
    await server.app.engine.dispose()


def evidence_warnings(caplog):
    return [r for r in caplog.records if "routing evidence" in r.getMessage().lower()]


def verified_doc(as_of: str):
    """A valid override whose figure is verified, so only the age can warn."""
    today = datetime.now(UTC).date().isoformat()
    scores = {"a/cheap": {"b3": figure(80, as_of=as_of, verified=today)}}
    return document(scores=scores, as_of=as_of)


async def test_evidence_older_than_90_days_warns_once_naming_the_date_and_changes_nothing(
    make_settings, monkeypatch, caplog, tmp_path, restore_logging
):
    old = (datetime.now(UTC) - timedelta(days=91)).date().isoformat()
    data = tmp_path / "data"
    data.mkdir()
    (data / ev.FILENAME).write_text(json.dumps(verified_doc(old)))
    with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro"):
        cfg, server = boot(make_settings, monkeypatch, routing="dynamic")
    (warning,) = evidence_warnings(caplog)
    assert old in warning.getMessage() and "91 days" in warning.getMessage()
    assert server.app.evidence.snapshot().origin == "file"
    await close(server)


async def test_evidence_exactly_90_days_old_does_not_warn(
    make_settings, monkeypatch, caplog, tmp_path, restore_logging
):
    edge = (datetime.now(UTC) - timedelta(days=90)).date().isoformat()
    data = tmp_path / "data"
    data.mkdir()
    (data / ev.FILENAME).write_text(json.dumps(verified_doc(edge)))
    with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro"):
        _, server = boot(make_settings, monkeypatch, routing="dynamic")
    assert evidence_warnings(caplog) == []
    await close(server)


async def test_evidence_with_no_verified_score_warns_that_nothing_is_verified(
    make_settings, monkeypatch, caplog, tmp_path, restore_logging
):
    data = tmp_path / "data"
    data.mkdir()
    (data / ev.FILENAME).write_text(json.dumps(document(as_of="2026-11-01")))  # empty scores
    with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro"):
        _, server = boot(make_settings, monkeypatch, routing="dynamic")
    (warning,) = evidence_warnings(caplog)
    assert "no verified routing evidence" in warning.getMessage()
    assert "fall back" in warning.getMessage()
    await close(server)


async def test_the_packaged_evidence_holds_verified_scores_and_warns_nothing(
    make_settings, monkeypatch, caplog, restore_logging
):
    with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro"):
        _, server = boot(make_settings, monkeypatch, routing="dynamic")
    # no "no verified evidence" warning (an age warning is the packaged file getting old)
    assert not [w for w in evidence_warnings(caplog) if "no verified" in w.getMessage()]
    await close(server)


@pytest.mark.parametrize("mode", ["standard", "custom"])
async def test_other_modes_read_no_evidence_and_warn_nothing_about_a_corrupt_file(
    make_settings, monkeypatch, caplog, tmp_path, restore_logging, mode
):
    data = tmp_path / "data"
    data.mkdir()
    (data / ev.FILENAME).write_text("not json at all")
    extra = {}
    if mode == "custom":
        extra = dict(tier_light="x/l", tier_standard="x/s", tier_complex="x/c")

    def boom(*args, **kwargs):
        raise AssertionError("the evidence was read")

    monkeypatch.setattr(ev, "load", boom)
    with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro"):
        _, server = boot(make_settings, monkeypatch, routing=mode, **extra)
    assert evidence_warnings(caplog) == []
    assert (data / ev.FILENAME).read_text() == "not json at all"
    await close(server)


async def test_a_one_shot_command_in_dynamic_mode_emits_no_startup_warning(
    make_settings, monkeypatch, caplog, restore_logging
):
    def boom(*args, **kwargs):
        raise AssertionError("the evidence was read")

    monkeypatch.setattr(ev, "load", boom)
    with caplog.at_level(logging.WARNING, logger="mcp_perplexity_pro"):
        _, server = boot(make_settings, monkeypatch, serving=False, routing="dynamic")
    assert evidence_warnings(caplog) == []
    await close(server)


def test_a_serving_process_in_standard_mode_logs_no_evidence_line_end_to_end(tmp_path):
    env = server_env(tmp_path, PERPLEXITY_ROUTER_MARGIN="abc")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / ev.FILENAME).write_text("garbage")
    done = subprocess.run(
        [sys.executable, "-m", "mcp_perplexity_pro", "--transport", "stdio"],
        env=env,
        capture_output=True,
        text=True,
        input="",
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert "routing evidence" not in done.stderr
    warned = [ln for ln in done.stderr.splitlines() if "PERPLEXITY_ROUTER_MARGIN" in ln]
    assert len(warned) == 1 and "WARNING" in warned[0] and "abc" not in warned[0]


def test_a_dynamic_process_with_a_bad_margin_exits_naming_the_variable(tmp_path):
    env = server_env(tmp_path, PERPLEXITY_ROUTING="dynamic", PERPLEXITY_ROUTER_MARGIN="25")
    done = subprocess.run(
        [sys.executable, "-m", "mcp_perplexity_pro", "--transport", "stdio"],
        env=env,
        capture_output=True,
        text=True,
        input="",
        timeout=60,
    )
    assert done.returncode != 0
    assert "PERPLEXITY_ROUTER_MARGIN" in done.stderr and "0 to 20" in done.stderr
    assert not (tmp_path / "data").exists()

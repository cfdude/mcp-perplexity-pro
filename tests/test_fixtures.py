"""Hygiene checks for recorded API fixtures under ``tests/fixtures/``."""

import json
import re

import pytest
from fixture_support import FIXTURE_DIR, REQUIRED_META_KEYS, find_key_shapes

PAYLOADS = sorted(p for p in FIXTURE_DIR.glob("*.json") if not p.name.endswith(".meta.json"))
SIDECARS = sorted(FIXTURE_DIR.glob("*.meta.json"))
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def test_fixtures_exist():
    assert PAYLOADS, "no fixtures recorded"


@pytest.mark.parametrize("path", [*PAYLOADS, *SIDECARS], ids=lambda p: p.name)
def test_no_key_shaped_strings(path):
    hits = find_key_shapes(path.read_text())
    assert not hits, f"{path.name} contains key-shaped strings: {hits}"


@pytest.mark.parametrize("path", PAYLOADS, ids=lambda p: p.name)
def test_payload_has_complete_sidecar(path):
    json.loads(path.read_text())
    sidecar = path.with_suffix(".meta.json")
    assert sidecar.exists(), f"{path.name} has no {sidecar.name}"
    meta = json.loads(sidecar.read_text())
    missing = [k for k in REQUIRED_META_KEYS if meta.get(k) in (None, "", [])]
    assert not missing, f"{sidecar.name} is missing {missing}"
    assert isinstance(meta["http_status"], int)
    assert DATE.match(meta["capture_date"])
    assert meta["endpoint"].startswith("/")
    assert meta["method"] in {"GET", "POST"}


@pytest.mark.parametrize("sidecar", SIDECARS, ids=lambda p: p.name)
def test_sidecar_has_payload(sidecar):
    payload = sidecar.with_name(sidecar.name.removesuffix(".meta.json") + ".json")
    assert payload.exists(), f"{sidecar.name} has no fixture {payload.name}"


def test_key_scan_detects_a_key():
    assert find_key_shapes("x pplx-" + "A1" * 12 + " y")
    assert not find_key_shapes("pplx-short")

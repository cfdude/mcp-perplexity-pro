"""Live capture helper: records scrubbed API fixtures into ``tests/fixtures/``.

Run deliberately with a real key in the environment (never stored in the repo)::

    PERPLEXITY_API_KEY=... uv run pytest -m live tests/test_live_capture.py

Every payload is key-scanned BEFORE any file is written; a hit aborts the whole run with
nothing written. Set ``FIXTURE_RAW_DIR`` to also keep unscrubbed raw copies OUTSIDE the repo
(they hold account identifiers, so they must never be committed).
"""

import json
import os
import re
import time
from datetime import date
from pathlib import Path

import httpx2
import pytest
from fixture_support import FIXTURE_DIR, find_key_shapes

pytestmark = [pytest.mark.live, pytest.mark.allow_network]

BASE_URL = "https://api.perplexity.ai"
PROMPT = "What is the current stable version of Python? One sentence."
TERMINAL = {"completed", "failed", "cancelled", "canceled", "expired", "incomplete"}
# Dict keys whose values identify an account, user, organization or end user.
ACCOUNT_KEY = re.compile(
    r"user|org|account|email|safety|customer|tenant|workspace|key_id|api_key", re.I
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PLACEHOLDER = "<scrubbed>"


def scrub(value, path: str, removed: list[str]):
    """Replace account-identifying values with a placeholder, recording each path."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            here = f"{path}.{k}" if path else k
            if ACCOUNT_KEY.search(k) and v is not None and not isinstance(v, bool):
                removed.append(here)
                out[k] = PLACEHOLDER
            else:
                out[k] = scrub(v, here, removed)
        return out
    if isinstance(value, list):
        return [scrub(v, f"{path}[]", removed) for v in value]
    if isinstance(value, str) and EMAIL.search(value):
        removed.append(path)
        return EMAIL.sub(PLACEHOLDER, value)
    return value


def _body(resp: httpx2.Response):
    try:
        return resp.json()
    except ValueError:
        return {"_non_json_body": resp.text}


def test_capture_fixtures():
    key = os.environ.get("PERPLEXITY_API_KEY")
    if not key:
        pytest.skip("PERPLEXITY_API_KEY is not set")
    today = date.today().isoformat()
    raw_dir = os.environ.get("FIXTURE_RAW_DIR")
    pending: dict[str, tuple[dict, dict]] = {}  # name -> (payload, meta)
    notes: dict[str, object] = {}

    def record(name, resp, method, endpoint, extra=None):
        body = _body(resp)
        if raw_dir:
            Path(raw_dir).mkdir(parents=True, exist_ok=True)
            (Path(raw_dir) / f"{name}.json").write_text(json.dumps(body, indent=2))
        removed: list[str] = []
        payload = scrub(body, "", removed)
        meta = {
            "endpoint": endpoint,
            "method": method,
            "http_status": resp.status_code,
            "capture_date": today,
            "content_type": resp.headers.get("content-type"),
            "scrubbed": removed or "nothing: no account-specific values were present",
            "note": "Response ids are kept; they identify no account. Request headers and "
            "the API key are never recorded.",
        }
        if extra:
            meta.update(extra)
        pending[name] = (payload, meta)

    auth = {"Authorization": f"Bearer {key}"}
    with httpx2.Client(base_url=BASE_URL, timeout=httpx2.Timeout(30.0, read=120.0)) as c:
        record("models", c.get("/v1/models", headers=auth), "GET", "/v1/models")
        record(
            "models_unauthenticated",
            c.get("/v1/models"),
            "GET",
            "/v1/models",
            {"request_note": "sent with no Authorization header"},
        )
        record(
            "agent_fast",
            c.post("/v1/agent", headers=auth, json={"preset": "fast", "input": PROMPT}),
            "POST",
            "/v1/agent",
            {"request_note": "preset fast, short prompt"},
        )

        submit = c.post(
            "/v1/agent", headers=auth, json={"preset": "fast", "input": PROMPT, "background": True}
        )
        record(
            "agent_background_submit",
            submit,
            "POST",
            "/v1/agent",
            {"request_note": "preset fast, background true"},
        )
        sbody = _body(submit)
        rid = sbody.get("id") if isinstance(sbody, dict) else None
        statuses = [sbody.get("status")] if isinstance(sbody, dict) else []
        if rid:
            poll_path = None
            first_seen = None
            deadline = time.monotonic() + 180
            final = None
            while time.monotonic() < deadline:
                candidates = (
                    [poll_path] if poll_path else [f"/v1/agent/{rid}", f"/v1/responses/{rid}"]
                )
                resp = None
                for p in candidates:
                    resp = c.get(p, headers=auth)
                    if resp.status_code != 404:
                        poll_path = p
                        break
                    notes.setdefault("poll_404_paths", []).append(p.replace(rid, "{id}"))
                st = _body(resp).get("status") if resp.status_code == 200 else None
                statuses.append(st)
                if first_seen is None and st not in TERMINAL:
                    first_seen = resp
                final = resp
                if resp.status_code != 200 or st in TERMINAL:
                    break
                time.sleep(3)
            if first_seen is not None and first_seen is not final:
                record(
                    "agent_background_poll_pending",
                    first_seen,
                    "GET",
                    (poll_path or "").replace(rid, "{id}"),
                )
            record(
                "agent_background_poll",
                final,
                "GET",
                (poll_path or "").replace(rid, "{id}"),
                {"statuses_observed": [s for s in statuses if s], **notes},
            )

        record(
            "chat_completions_403",
            c.post(
                "/chat/completions",
                headers=auth,
                json={"model": "sonar", "messages": [{"role": "user", "content": "hi"}]},
            ),
            "POST",
            "/chat/completions",
        )
        record(
            "async_chat_completions_403",
            c.get("/async/chat/completions", headers=auth, params={"limit": 1}),
            "GET",
            "/async/chat/completions",
        )
        record(
            "agent_anthropic_no_max_output_tokens_400",
            c.post(
                "/v1/agent",
                headers=auth,
                json={"model": "anthropic/claude-haiku-4-5", "input": "hi"},
            ),
            "POST",
            "/v1/agent",
            {"request_note": "model anthropic/claude-haiku-4-5, no max_output_tokens"},
        )

    # Key-shape scan of EVERY payload and sidecar before writing ANY file.
    for name, (payload, meta) in pending.items():
        hits = find_key_shapes(json.dumps(payload)) + find_key_shapes(json.dumps(meta))
        assert not hits, f"key-shaped string in {name}; nothing written"
    assert key not in json.dumps([p for p, _ in pending.values()]), "live key in a payload"

    FIXTURE_DIR.mkdir(exist_ok=True)
    for name, (payload, meta) in pending.items():
        (FIXTURE_DIR / f"{name}.json").write_text(json.dumps(payload, indent=2) + "\n")
        (FIXTURE_DIR / f"{name}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")

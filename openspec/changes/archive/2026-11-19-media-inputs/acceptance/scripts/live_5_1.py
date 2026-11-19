#!/usr/bin/env python3
"""media-inputs task 5.1: the live acceptance run, driven through the `perplexity-pro` command.

Reads PERPLEXITY_API_KEY from the environment (never printed, written or required here); every
output is passed through `redact_text` before it is saved. Uses a temporary data directory and a
separate temporary directory for the files to attach (the data directory is on the deny list: `c_denied_path` attaches an existing file in it, so the
deny list answers, not a missing-file error).
Stops when the summed reported cost reaches COST_STOP. Run from the repository root:

    PERPLEXITY_API_KEY=... uv run python openspec/changes/media-inputs/acceptance/scripts/live_5_1.py
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

import media_support as ms  # noqa: E402

from mcp_perplexity_pro.redaction import redact_text  # noqa: E402

OUT = ROOT / "openspec/changes/media-inputs/acceptance/live-5-1"
KEY = os.environ["PERPLEXITY_API_KEY"]
COST_STOP = Decimal("0.25")
LUNA = "openai/gpt-6-luna"
REFUSES_DOC = "xai/grok-4.3"
IMG_URL = "https://www.python.org/static/img/python-logo.png"
PDF_URL = "https://pdfobject.com/pdf/sample.pdf"

DATA = Path(tempfile.mkdtemp(prefix="pplx-5-1-data-"))
FILES = Path(tempfile.mkdtemp(prefix="pplx-5-1-files-"))
OUTSIDE = Path(tempfile.mkdtemp(prefix="pplx-5-1-outside-"))
ROOTS = FILES
(FILES / "red.png").write_bytes(ms.png())
(FILES / "doc.pdf").write_bytes(ms.pdf("The secret word is MANGO"))
(FILES / "note.txt").write_bytes(b"The secret word is PAPAYA.\n")
(FILES / "audio.wav").write_bytes(ms.wav())
(OUTSIDE / "outside.txt").write_bytes(b"The secret word is KIWI.\n")
(DATA / "denied.txt").write_bytes(b"The secret word is GUAVA.\n")  # inside the data directory: on the deny list

ENV = {
    **os.environ,
    "PERPLEXITY_DATA_DIR": str(DATA),
    "PERPLEXITY_ATTACH_ROOTS": str(ROOTS),
    "PERPLEXITY_MATRIX_REFRESH": "0",
    "PERPLEXITY_MATRIX_PROBE": "off",
}
OUT.mkdir(parents=True, exist_ok=True)
spent = Decimal(0)
results: dict[str, dict] = {}


def clean(text: str) -> str:
    text = redact_text(text, (KEY,))
    for d, label in ((str(DATA), "<data>"), (str(FILES), "<files>"), (str(OUTSIDE), "<outside>")):
        text = text.replace(d, label)
    return text


def run(name: str, *args: str, env: dict | None = None) -> dict:
    global spent
    if spent >= COST_STOP:
        raise SystemExit(f"hard stop: ${spent} spent before {name}")
    proc = subprocess.run(
        ["uv", "run", "--quiet", "perplexity-pro", *args, "--json"],
        capture_output=True,
        text=True,
        env=env or ENV,
        cwd=ROOT,
        timeout=240,
    )
    out = clean(proc.stdout)
    try:
        body = json.loads(out)
    except ValueError:
        body = None
    cost = Decimal(0)
    if isinstance(body, dict):
        cost = Decimal((body.get("usage") or {}).get("cost_usd") or 0)
    spent += cost
    record = {
        "name": name,
        "argv": [clean(a) for a in args],
        "returncode": proc.returncode,
        "result": body,
        "stdout_raw": None if body is not None else out,
        "stderr": clean(proc.stderr).strip(),
        "cost_usd": str(cost),
    }
    (OUT / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")
    results[name] = record
    ans = (body or {}).get("answer") if isinstance(body, dict) else None
    print(f"{name}: rc={proc.returncode} cost={cost} answer={str(ans)[:70]!r} {record['stderr'][:150]}")
    return record


def ask(name: str, query: str, *attach: str, model: str | None = LUNA, depth: str | None = None):
    args = ["ask", query]
    args += ["--depth", depth] if depth else ["--model", model, "--no-search"]
    for a in attach:
        args += ["--attachments", a]
    return run(name, *args)


Q_COLOUR = "What colour is the attached image? One word."
Q_WORD = "What is the secret word in the attached document? One word."

# (a) ask: five attachment forms on a model and on a preset
for tag, kw in (("luna", {}), ("fast", {"depth": "fast"})):
    ask(f"a_{tag}_png", Q_COLOUR, str(FILES / "red.png"), **kw)
    ask(f"a_{tag}_pdf", Q_WORD, str(FILES / "doc.pdf"), **kw)
    ask(f"a_{tag}_txt", Q_WORD, str(FILES / "note.txt"), **kw)
    ask(f"a_{tag}_image_url", "What is shown in the attached image? A few words.", IMG_URL, **kw)
    ask(f"a_{tag}_pdf_url", "What is this document about? A few words.", PDF_URL, **kw)

# (b) and (f2): chat, chained, adds an image, a replay (warning), the file attached again
chat = ["chat", "send", "--model", LUNA, "--no-search"]
t1 = run("b_turn1_pdf", *chat, "--title", "acceptance", "--message", Q_WORD,
         "--attachments", str(FILES / "doc.pdf"))
cid = str((t1["result"] or {}).get("chat_id", ""))
if cid:
    run("b_turn2_chained_text", *chat, "--chat-id", cid, "--message",
        "Say hello in one word, and do not mention any file.")
    run("b_turn3_chained_asks_pdf", *chat, "--chat-id", cid, "--message",
        "What was the secret word in the first document? One word.")
    run("b_turn4_adds_image", *chat, "--chat-id", cid, "--message", Q_COLOUR,
        "--attachments", str(FILES / "red.png"))
    run("b_turn5_replay_no_file", *chat, "--chat-id", cid, "--replay", "--message",
        "Without any new file: what was the secret word in the first document? If you cannot "
        "see the document itself, answer exactly CANNOT SEE.")
    run("b_turn6_replay_file_again", *chat, "--chat-id", cid, "--replay", "--message", Q_WORD,
        "--attachments", str(FILES / "doc.pdf"))
    run("b_turn7_chained_after_restart", *chat, "--chat-id", cid, "--message",
        "What was the secret word in the document? One word.")

# (c) the refusals: a document to a model recorded as refusing documents, audio, outside the roots,
# a denied path, and a model that refuses documents as a failed run
run("c_model_refuses_document", "ask", "Summarize", "--model", REFUSES_DOC, "--attachments",
    str(FILES / "doc.pdf"))
run("c_audio", "ask", "Transcribe", "--model", LUNA, "--attachments", str(FILES / "audio.wav"))
run("c_outside_roots", "ask", Q_WORD, "--model", LUNA, "--attachments", str(OUTSIDE / "outside.txt"))
run("c_denied_path", "ask", Q_WORD, "--model", LUNA, "--attachments", str(DATA / "denied.txt"))
run("c_opus5_failed_refusal", "ask", Q_WORD, "--model", "anthropic/claude-opus-5",
    "--no-search", "--attachments", str(FILES / "doc.pdf"))

# (c2) a local refusal makes no request: the same call with the base URL pointing at a closed port
dead = {**ENV, "PERPLEXITY_BASE_URL": "http://127.0.0.1:9"}
run("c_local_refusal_no_request", "ask", "Summarize", "--model", REFUSES_DOC, "--attachments",
    str(FILES / "doc.pdf"), env=dead)

# (e) the models listing shows the inputs column (a read, free)
models = run("e_models", "models")
rows = (models["result"] or {}).get("models", [])
(OUT / "e_models_inputs.txt").write_text(
    "\n".join(f"{m['id']} | {m.get('inputs') or '-'}" for m in rows) + "\n"
)

# (f2) the HTTP transport: a path is refused without roots and accepted with them
def http_call(port: int, name: str, arguments: dict) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
    except urllib.error.HTTPError as exc:
        return {"http_error": exc.code, "body": exc.read().decode()[:500]}


def serve_http(port: int, roots: str | None):
    env = {**ENV, "PERPLEXITY_PORT": str(port)}
    if roots is None:
        env.pop("PERPLEXITY_ATTACH_ROOTS", None)
    else:
        env["PERPLEXITY_ATTACH_ROOTS"] = roots
    proc = subprocess.Popen(
        ["uv", "run", "--quiet", "mcp-perplexity-pro", "--transport", "http"],
        env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return proc
        except Exception:
            import time

            time.sleep(0.5)
    proc.terminate()
    raise SystemExit("http server did not start")


import socket  # noqa: E402

http_results = {}
for label, roots in (("no_roots", None), ("with_roots", str(ROOTS))):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = serve_http(port, roots)
    try:
        resp = http_call(port, "perplexity_ask", {
            "query": Q_WORD, "model": LUNA, "search": False,
            "attachments": [str(FILES / "doc.pdf")]})
    finally:
        proc.terminate()
        proc.wait(timeout=20)
    text = json.dumps(resp)
    http_results[label] = clean(text)[:1500]
    try:
        spent += Decimal(resp["result"]["structuredContent"]["usage"]["cost_usd"] or 0)
    except (KeyError, TypeError):
        pass
    print(f"f2_http_{label}: {http_results[label][:200]}")
(OUT / "f2_http.json").write_text(json.dumps(http_results, indent=2) + "\n")

# (d) usage reconciliation and the no-bytes scan
db = DATA / "perplexity.db"
con = sqlite3.connect(db)
events = con.execute(
    "select id, tool, status, model, preset, request_id, input_tokens, cost_nano_usd, "
    "cost_source from usage_events order by id"
).fetchall()
per_call = {}
for name, rec in results.items():
    body = rec["result"]
    if isinstance(body, dict) and body.get("response_id"):
        per_call[body["response_id"]] = (name, rec["cost_usd"])
lines = ["event | tool | status | model | request_id | cost_nano_usd | call | call cost_usd | match"]
mismatch = 0
reconciled = 0
for ev in events:
    call = per_call.get(ev[5])
    if call:
        nano = int(Decimal(call[1]) * 10**9)
        ok = nano == ev[7]
        reconciled += 1
        mismatch += 0 if ok else 1
        lines.append(f"{ev[0]} | {ev[1]} | {ev[2]} | {ev[3] or ev[4]} | {ev[5]} | {ev[7]} | "
                     f"{call[0]} | {call[1]} | {'yes' if ok else 'NO'}")
    else:
        lines.append(f"{ev[0]} | {ev[1]} | {ev[2]} | {ev[3] or ev[4]} | {ev[5]} | {ev[7]} | "
                     "(no matching result: http call, failed run or error) | - | -")
total_nano = con.execute("select coalesce(sum(cost_nano_usd),0) from usage_events").fetchone()[0]
usage_cli = run("d_usage", "usage")
lines.append("")
lines.append(f"events: {len(events)}; reconciled to a result: {reconciled}; mismatches: {mismatch}")
lines.append(f"sum of cost_nano_usd in the database: {total_nano} ({Decimal(total_nano) / 10**9} USD)")
lines.append(f"perplexity_usage total: {json.dumps((usage_cli['result'] or {}).get('totals', usage_cli['result']))[:400]}")
lines.append(f"sum of per-call cost_usd in the saved results: {spent} USD (includes http calls)")

# no attachment byte or base64 in the database, the logs or the saved outputs
needles = {
    "pdf body line": b"The secret word is MANGO",
    "pdf header": b"%PDF-",
    "pdf base64 prefix": __import__("base64").b64encode(ms.pdf("The secret word is MANGO"))[:40],
    "png base64 prefix": __import__("base64").b64encode(ms.png())[:40],
    "txt body": b"The secret word is PAPAYA",
}
scan = []
for label, needle in needles.items():
    in_db = needle in db.read_bytes()
    for wal in DATA.glob("perplexity.db-*"):
        in_db = in_db or needle in wal.read_bytes()
    in_logs = any(needle in (clean(r["stderr"])).encode() for r in results.values())
    scan.append(f"{label}: in database {in_db}; in saved stderr {in_logs}")
chat_rows = con.execute("select role, content from chat_messages order by id").fetchall()
lines.append("")
lines.append("no-bytes scan (needle | database | saved stderr; an answer may say just MANGO, which is not a "
             "file byte):")
lines += scan
lines.append("")
lines.append("stored chat messages (role | content):")
lines += [f"{r} | {c!r}" for r, c in chat_rows]
con.close()
(OUT / "d_reconciliation.txt").write_text("\n".join(lines) + "\n")
print("\n".join(lines[-40:]))
print(f"TOTAL SPEND (reported, summed from results): ${spent}")

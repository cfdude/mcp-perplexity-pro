import json, sys, os
sys.argv = ["x", "NONE"]
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe.py")).read().split("M = \"openai")[0])
from concurrent.futures import ThreadPoolExecutor
models = list(json.load(open(os.environ["BASELINE_JSON"]))["models"])
def one(args):
    m, kind = args
    part = ({"type": "input_image", "image_url": "data:image/png;base64," + b64(RED)} if kind == "image"
            else {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF)})
    q = "What colour is this image? One word." if kind == "image" else "What is the secret word in the document? One word."
    req = urllib.request.Request("https://api.perplexity.ai/v1/agent", data=json.dumps({"model": m, "max_output_tokens": 150, "store": False, "input": user([T(q), part])}).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=150); code = r.status; j = json.loads(r.read())
    except urllib.error.HTTPError as e:
        code = e.code
        try: j = json.loads(e.read())
        except Exception: j = {}
    except Exception as e:
        return m, kind, {"code": 0, "err": str(e)[:100]}
    text = json.dumps(j.get("output"))[:2000].lower() if code == 200 else ""
    ok = ("red" in text) if kind == "image" else ("mango" in text)
    return m, kind, {"code": code, "st": j.get("status"), "ok": ok, "err": (j.get("error") or {}).get("message"), "cost": ((j.get("usage") or {}).get("cost") or {}).get("total_cost"), "in": (j.get("usage") or {}).get("input_tokens")}
jobs = [(m, k) for m in models for k in ("image", "file")]
res = {}
with ThreadPoolExecutor(6) as ex:
    for m, k, r in ex.map(one, jobs):
        res.setdefault(m, {})[k] = r
json.dump(res, open(OUT + "/sweep.json", "w"), indent=1)
tot = 0
for m, d in res.items():
    for k, r in d.items(): tot += r.get("cost") or 0
    print(m, "|", *[f"{k}:{r['code']}/{r.get('st')}/ok={r.get('ok')}/{(r.get('err') or '')[:60]}" for k, r in d.items()])
print("total cost", tot)

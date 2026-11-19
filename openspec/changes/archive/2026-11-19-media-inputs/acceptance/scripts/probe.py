import base64, json, os, struct, sys, urllib.request, urllib.error, zlib, wave, io
KEY = os.environ["PERPLEXITY_API_KEY"]
OUT = os.path.dirname(os.path.abspath(__file__))

def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def ch(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d))
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")

def pdf(text):
    s = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(s) + s + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = b"%PDF-1.4\n"; offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out); out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs: out += b"%010d 00000 n \n" % o
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, x)

def wav():
    b = io.BytesIO(); w = wave.open(b, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b"\x00\x00" * 800); w.close(); return b.getvalue()

b64 = lambda b: base64.b64encode(b).decode()
RED = png(48, 48, (255, 0, 0))
BIG = png(300, 300, (0, 0, 255))
PDF = pdf("The secret word is MANGO")
TXT = b"The secret word is PAPAYA.\n"

def call(label, body, path="/v1/agent"):
    req = urllib.request.Request("https://api.perplexity.ai" + path, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=120); code = r.status; txt = r.read().decode()
    except urllib.error.HTTPError as e:
        code = e.code; txt = e.read().decode()
    try: j = json.loads(txt)
    except Exception: j = {"raw": txt[:500]}
    open(f"{OUT}/{label}.json", "w").write(json.dumps({"status": code, "body": j}, indent=1))
    summ = {}
    if isinstance(j, dict):
        if "error" in j: summ["error"] = j["error"]
        if "usage" in j: summ["usage"] = j["usage"]
        summ["id"] = j.get("id"); summ["model"] = j.get("model"); summ["st"] = j.get("status")
        out = j.get("output")
        if out: summ["text"] = json.dumps(out)[:300]
        if "raw" in j: summ["raw"] = j["raw"]
    print(label, code, json.dumps(summ)[:900]); sys.stdout.flush()
    return j

def user(parts): return [{"role": "user", "content": parts}]
T = lambda s: {"type": "input_text", "text": s}
M = "openai/gpt-6-luna"
cases = sys.argv[1:]
def run(n):
    return not cases or n in cases

if run("A"): call("A_image_datauri_bare", {"model": M, "max_output_tokens": 60, "store": False, "input": user([T("What colour is this image? One word."), {"type": "input_image", "image_url": "data:image/png;base64," + b64(RED)}])})
if run("A2"): call("A2_image_message_item", {"model": M, "max_output_tokens": 60, "store": False, "input": [{"type": "message", "role": "user", "content": [T("What colour is this image? One word."), {"type": "input_image", "image_url": "data:image/png;base64," + b64(RED)}]}]})
if run("J"): call("J_image_big_datauri", {"model": M, "max_output_tokens": 60, "store": False, "input": user([T("Colour? One word."), {"type": "input_image", "image_url": "data:image/png;base64," + b64(BIG)}])})
if run("B"): call("B_image_https", {"model": M, "max_output_tokens": 60, "store": False, "input": user([T("Describe in 5 words."), {"type": "input_image", "image_url": "https://www.python.org/static/img/python-logo.png"}])})
if run("C"): call("C_file_b64_pdf", {"model": M, "max_output_tokens": 60, "store": True, "input": user([T("What is the secret word? One word."), {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF)}])})
if run("C2"): call("C2_file_store_false", {"model": M, "max_output_tokens": 60, "store": False, "input": user([T("What is the secret word? One word."), {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF)}])})
if run("D"): call("D_file_txt_datauri", {"model": M, "max_output_tokens": 60, "store": True, "input": user([T("What is the secret word? One word."), {"type": "input_file", "filename": "note.txt", "file_data": "data:text/plain;base64," + b64(TXT)}])})
if run("E"): call("E_file_url", {"model": M, "max_output_tokens": 60, "store": True, "input": user([T("What is this document about? 8 words."), {"type": "input_file", "file_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"}])})
if run("F"): call("F_audio", {"model": "google/gemini-3.5-flash-lite", "max_output_tokens": 60, "store": False, "input": user([T("Is there speech? One word."), {"type": "input_audio", "input_audio": {"data": b64(wav()), "format": "wav"}}])})
if run("G"):
    for m in ["perplexity/nemotron-3.5-super-120b-a12b", "perplexity/deepseek-v4-pro-0813", "perplexity/sonar"]:
        call("G_image_" + m.split("/")[1][:12], {"model": m, "max_output_tokens": 60, "store": False, "input": user([T("Colour? One word."), {"type": "input_image", "image_url": "data:image/png;base64," + b64(RED)}])})
if run("H"): call("H_file_with_websearch", {"model": M, "max_output_tokens": 60, "store": True, "tools": [{"type": "web_search"}], "max_steps": 3, "input": user([T("Secret word? One word."), {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF)}])})
if run("I"): call("I_image_preset_fast", {"effort": "fast", "max_output_tokens": 200, "store": False, "input": user([T("Colour? One word."), {"type": "input_image", "image_url": "data:image/png;base64," + b64(RED)}])})
if run("K"): call("K_bad_ext", {"model": M, "max_output_tokens": 60, "store": True, "input": user([T("hi"), {"type": "input_file", "filename": "doc.docx", "file_data": b64(PDF)}])})
if run("L"): call("L_bad_b64", {"model": M, "max_output_tokens": 60, "store": True, "input": user([T("hi"), {"type": "input_file", "filename": "doc.pdf", "file_data": "!!!notbase64!!!"}])})
if run("N"): call("N_both", {"model": M, "max_output_tokens": 60, "store": True, "input": user([T("hi"), {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF), "file_url": "https://example.com/a.pdf"}])})

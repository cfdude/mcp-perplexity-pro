import json, os, sys, time, random
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe.py")).read().split('M = "openai')[0]
sys.argv = ["x", "NONE"]
exec(src)
M = "openai/gpt-6-luna"
cases = set(sys.argv_cases) if hasattr(sys, "argv_cases") else None
def noisy_png(w, h):
    random.seed(1); raw = b"".join(b"\x00" + bytes(random.getrandbits(8) for _ in range(w * 3)) for _ in range(h))
    def ch(t, d):
        c = struct.pack(">I", len(d)) + t + d; return c + struct.pack(">I", zlib.crc32(t + d))
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")
NOISY = noisy_png(40, 40)  # ~4.8 KB, base64 > 6000 chars
print("noisy b64 chars", len(b64(NOISY)))
IMG = lambda b, mt="image/png": {"type": "input_image", "image_url": f"data:{mt};base64," + b64(b)}
base = {"model": M, "max_output_tokens": 200, "store": False}
r = call("P1_image_over_2048_chars", {**base, "input": user([T("Say ok."), IMG(NOISY)])}); time.sleep(3)
r = call("P2_image_wrong_mime", {**base, "input": user([T("Colour? One word."), IMG(RED, "image/jpeg")])}); time.sleep(3)
r = call("P3_image_svg", {**base, "input": user([T("Say ok."), IMG(b"<svg xmlns='http://www.w3.org/2000/svg' width='4' height='4'/>", "image/svg+xml")])}); time.sleep(3)
r = call("P4_image_bmp", {**base, "input": user([T("Say ok."), IMG(b"BM" + b"\0" * 60, "image/bmp")])}); time.sleep(3)
r = call("P5_image_http_url", {**base, "input": user([T("Say ok."), {"type": "input_image", "image_url": "http://www.python.org/static/img/python-logo.png"}])}); time.sleep(3)
r = call("P6_two_images_one_doc", {**base, "input": user([T("Colours of the two images and the secret word in the doc, 3 words."), IMG(RED), IMG(BIG), {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF)}])}); time.sleep(3)
# continuation: store true doc then follow-up
r1 = call("P7a_doc_store_true", {**base, "store": True, "input": user([T("Remember the secret word in the doc. Say ok."), {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF)}])}); time.sleep(3)
if r1.get("id"):
    call("P7b_followup_chained", {**base, "store": False, "previous_response_id": r1["id"], "input": "What was the secret word? One word."}); time.sleep(3)
r2 = call("P8a_doc_store_false", {**base, "store": False, "input": user([T("Remember the secret word in the doc. Say ok."), {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF)}])}); time.sleep(3)
if r2.get("id"):
    call("P8b_followup_after_store_false", {**base, "store": False, "previous_response_id": r2["id"], "input": "What was the secret word? One word."}); time.sleep(3)
# image continuation
r3 = call("P9a_image_store_true", {**base, "store": True, "input": user([T("Remember the colour of the image. Say ok."), IMG(RED)])}); time.sleep(3)
if r3.get("id"):
    call("P9b_image_followup", {**base, "store": False, "previous_response_id": r3["id"], "input": "What colour was the image? One word."}); time.sleep(3)
# https image and url file, enough tokens to finish
call("P10_image_https_full", {**base, "max_output_tokens": 800, "input": user([T("Describe the logo in 6 words."), {"type": "input_image", "image_url": "https://www.python.org/static/img/python-logo.png"}])}); time.sleep(3)
call("P11_file_url_full", {**base, "max_output_tokens": 800, "input": user([T("Quote the first 8 words of the document."), {"type": "input_file", "file_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"}])}); time.sleep(3)
call("P12_file_url_http", {**base, "input": user([T("Say ok."), {"type": "input_file", "file_url": "http://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"}])}); time.sleep(3)
call("P13_file_mislabeled_pdf_as_txt", {**base, "input": user([T("Say ok."), {"type": "input_file", "filename": "a.txt", "file_data": b64(PDF)}])}); time.sleep(3)
call("P14_file_empty", {**base, "input": user([T("Say ok."), {"type": "input_file", "filename": "a.pdf", "file_data": ""}])}); time.sleep(3)
call("P15_audio_as_file", {**base, "input": user([T("Say ok."), {"type": "input_file", "filename": "a.wav", "file_data": b64(wav())}])}); time.sleep(3)
call("P16_input_video", {**base, "input": user([T("Say ok."), {"type": "input_video", "video_url": "https://example.com/a.mp4"}])}); time.sleep(3)
call("P17_audio_url_part", {**base, "input": user([T("Say ok."), {"type": "input_audio", "audio_url": "https://example.com/a.mp3"}])}); time.sleep(3)
# research (background) with a document
r4 = call("P18_background_research_doc", {"effort": "medium", "background": True, "store": True, "max_output_tokens": 300, "input": user([T("What is the secret word in the attached document? One word."), {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF)}])}); time.sleep(3)
if r4.get("id"):
    time.sleep(40)
    req = urllib.request.Request("https://api.perplexity.ai/v1/agent/" + r4["id"], headers={"Authorization": "Bearer " + KEY})
    try: j = json.loads(urllib.request.urlopen(req, timeout=60).read())
    except urllib.error.HTTPError as e: j = {"http": e.code}
    open(OUT + "/P18b_poll.json", "w").write(json.dumps(j, indent=1)); print("P18b", j.get("status"), json.dumps(j.get("error")), json.dumps(j.get("output"))[:300])

time.sleep(3)
call("P19_fast_doc", {"effort": "fast", "max_output_tokens": 300, "store": False, "input": user([T("What is the secret word in the document? One word."), {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF)}])}); time.sleep(3)
call("P19b_low_image", {"effort": "low", "max_output_tokens": 300, "store": False, "input": user([T("Colour of the image? One word."), IMG(RED)])}); time.sleep(3)
call("P19c_medium_image", {"effort": "medium", "max_output_tokens": 300, "store": False, "input": user([T("Colour of the image? One word."), IMG(RED)])}); time.sleep(3)
if r3.get("id"):
    call("P20_chain_adds_new_image", {**base, "store": False, "previous_response_id": r3["id"], "input": user([T("What colour is the NEW image, and what colour was the first? Two words."), IMG(BIG)])}); time.sleep(3)
for m, k in [("anthropic/claude-opus-5", "file"), ("perplexity/glm-5.3", "file"), ("perplexity/glm-5.3-flash", "file"), ("perplexity/kimi-k3", "file")]:
    call("R_" + m.split("/")[1] + "_" + k, {"model": m, "max_output_tokens": 150, "store": False, "input": user([T("What is the secret word in the document? One word."), {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF)}])}); time.sleep(4)

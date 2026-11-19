import os, sys, json
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe.py")).read().split('M = "openai')[0]
sys.argv = ["x", "NONE"]
exec(src)
import time
D = os.path.join(OUT, "docs")
for name in ["k.doc", "k.docx", "k.rtf"]:
    b = open(os.path.join(D, name), "rb").read()
    call("Q_" + name.replace(".", "_"), {"model": "openai/gpt-6-luna", "max_output_tokens": 200, "store": False, "input": user([T("What is the secret word in the document? One word."), {"type": "input_file", "filename": name, "file_data": b64(b)}])})
    time.sleep(4)

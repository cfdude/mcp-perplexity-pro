import os, sys, json, time
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe.py")).read().split('M = "openai')[0]
sys.argv = ["x", "NONE"]
exec(src)
M = "openai/gpt-6-luna"; base = {"model": M, "max_output_tokens": 200, "store": False}
r1 = call("S1_doc_turn", {**base, "input": user([T("Remember the secret word in the doc. Say ok."), {"type": "input_file", "filename": "doc.pdf", "file_data": b64(PDF)}])}); time.sleep(3)
r2 = call("S2_text_turn_chained", {**base, "previous_response_id": r1["id"], "input": "Say ok again."}); time.sleep(3)
r3 = call("S3_third_turn_chained_asks_doc", {**base, "previous_response_id": r2["id"], "input": "What was the secret word in the document? One word."}); time.sleep(3)
# a different model on the follow-up (does a model switch keep the file?)
call("S4_model_switch_followup", {"model": "google/gemini-3.6-flash", "max_output_tokens": 200, "store": False, "previous_response_id": r2["id"], "input": "What was the secret word in the document? One word."})

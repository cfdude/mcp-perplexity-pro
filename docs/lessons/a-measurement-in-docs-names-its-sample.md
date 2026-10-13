---
name: a-measurement-in-docs-names-its-sample
kind: process-failure
trigger: Writing a cost, latency or numbering claim into the README, a tool description or a spec from a handful of recorded runs of one query.
cost: In py-agent-api the docs said medium research took about 35 to 40 s and cost $0.016 to $0.017, from two runs of one narrow query. A live run in another project took about 90 s and cost $0.023, and ours later took 71 s and $0.02524. The same pattern put "the markers are not numbered like the ids" in the README from one fixture; three markers in a research fixture show the opposite. Both were found by a user's live run, not by us.
enforced_in: task 3.1 and the Gate 2 documentation check of py-agent-citation-fixes (a range in the docs must name how many runs and which query shape stand behind it; the acceptance README lists every run).
---

When a figure or a rule in the docs rests on fewer than five observations, say so beside the
figure ("two runs of one query") and name what drives the number (here: how many fetches and
searches the run makes). Prefer "observed N runs, range X to Y" over "about X". Re-check the claim
against the committed fixtures with `jq` before writing a rule about response shape.

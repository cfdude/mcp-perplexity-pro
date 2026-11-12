#!/usr/bin/env python3
"""Owner-run OFFLINE worksheet: print vendor-reported benchmarks for the router shortlist as LEADS.

LLM Stats (llm-stats.com) is a LEADS source only (routing-v2 design D2, task 2.2): its Community
plan forbids redistribution, none of its rows is verified and it lists no Sonar model. This script
therefore

* reads the key from the environment variable ``LLM_STATS_API_KEY`` (never committed, never
  printed, never logged);
* calls ``GET /stats/v1/models/{id}`` once per shortlist model that has an entry in the hand-kept
  table below (about 12 data responses of the 250 a day) and NEVER ``/v1/scores``;
* prints, per model, each benchmark the VENDOR reported with its ``source_url`` and the line
  ``Data by LLM Stats (linked to https://llm-stats.com)``;
* writes to stdout only, and writes nothing into ``src/``. Redirected output belongs under the
  gitignored ``acceptance/llm_stats_*.txt``.

A figure printed here is a lead. It becomes a score of ``data/routing_evidence.json`` only after a
human opened the ``source_url`` (the vendor or benchmark page), read the number, the benchmark
version and the date, and wrote ``verified_at``. Never copy a row or text of this output into the
repository.

Usage::

    LLM_STATS_API_KEY=... python3 llm_stats_leads.py > llm_stats_2026-11-11.txt
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://api.llm-stats.com/stats/v1"
ATTRIBUTION = "Data by LLM Stats (linked to https://llm-stats.com)"

# Our id -> LLM Stats ``model_id``: a hand-kept table (the join rule has a false-match risk, so it
# is never computed). ``None`` means LLM Stats has no such model (Sonar is hosted by Perplexity).
MODEL_IDS: dict[str, str | None] = {
    "openai/gpt-6-luna": "gpt-6-luna",
    "anthropic/claude-haiku-5-5": "claude-haiku-5-5",
    "perplexity/sonar": None,
    "google/gemini-3.8-flash": "gemini-3.8-flash",
    "anthropic/claude-sonnet-5-5": "claude-sonnet-5-5",
    "openai/gpt-6.1-sol": "gpt-6.1-sol",
    "openai/gpt-6.1-terra": "gpt-6.1-terra",
    "anthropic/claude-opus-5-5": "claude-opus-5-5",
}

# The benchmarks of the three task classes (their ids on LLM Stats, hyphenated). ``gpqa`` there is a
# 448-question set and is NOT Diamond: it is printed for context and never entered as Diamond.
WANTED = (
    "swe-bench-pro",
    "terminal-bench-4.0",
    "gpqa-diamond",
    "gpqa",
    "browsecomp",
)


def get(path: str, key: str) -> dict:
    request = urllib.request.Request(
        BASE + path, headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "llm-stats-leads-worksheet/1.0",  # the default urllib agent is refused
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        return {"_error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"_error": type(exc).__name__}


def scores_of(model: dict) -> list[dict]:
    """The embedded score rows of a model response, whatever the field is called."""
    for name in ("scores", "benchmarks", "benchmark_scores"):
        rows = model.get(name)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def main() -> int:
    key = os.environ.get("LLM_STATS_API_KEY", "")
    if not key:
        print("LLM_STATS_API_KEY is not set", file=sys.stderr)
        return 2
    print("# Leads only: open each source_url and read the figure before entering anything.")
    print(f"# {ATTRIBUTION}\n")
    for ours, theirs in MODEL_IDS.items():
        print(f"## {ours}")
        if theirs is None:
            print("no LLM Stats model (hosted by Perplexity); source its figures elsewhere\n")
            continue
        body = get(f"/models/{theirs}", key)
        if "_error" in body:
            print(f"lookup failed: {body['_error']}\n")
            continue
        rows = scores_of(body)
        shown = 0
        for row in rows:
            bench = str(row.get("benchmark_id") or row.get("benchmark") or row.get("id") or "")
            if bench.lower() not in WANTED:
                continue
            shown += 1
            print(
                f"- {bench}: score={row.get('score')} self_reported={row.get('is_self_reported')}"
                f" source_url={row.get('source_url')} verified_by_llmstats={row.get('verified')}"
            )
        if not shown:
            print(f"none of {', '.join(WANTED)} reported ({len(rows)} rows seen)")
        print()
    print(f"# {ATTRIBUTION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

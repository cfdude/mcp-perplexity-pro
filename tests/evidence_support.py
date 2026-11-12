"""Small evidence literals for the router tests: a valid document built from keyword arguments,
so a test changes one thing and nothing is read from a file."""

import copy
import json
from datetime import date
from typing import Any

from mcp_perplexity_pro import routing_evidence as ev

TODAY = date(2026, 11, 11)


def figure(score: Any = 70, *, verified: str | None = "2026-11-10", **over: Any) -> dict[str, Any]:
    out = {
        "score": score,
        "source_url": "https://vendor.example/results",
        "as_of": "2026-11-01",
        "basis": "vendor",
        "harness": None,
        "verified_at": verified,
    }
    out.update(over)
    return out


def document(
    *,
    scores: dict[str, dict[str, Any]] | None = None,
    classes: dict[str, list[str]] | None = None,
    shortlist: list[str] | None = None,
    fallback: str = "a/cheap",
    **over: Any,
) -> dict[str, Any]:
    """A valid evidence document. ``scores`` maps a model id to ``{benchmark: figure}``."""
    ids = shortlist if shortlist is not None else ["a/cheap", "b/mid", "c/top"]
    classes = classes if classes is not None else {"coding": ["b1", "b2"], "browsing": ["b3"]}
    benchmarks = {name for names in classes.values() for name in names} | {"b1", "b2", "b3"}
    doc: dict[str, Any] = {
        "version": 1,
        "as_of": "2026-11-01",
        "task_classes": {name: {"benchmarks": list(ids_)} for name, ids_ in classes.items()},
        "benchmarks": {name: {"name": name.upper()} for name in sorted(benchmarks)},
        "shortlist": list(ids),
        "fallbacks": {"default": {"model": fallback, "effort": "low"}},
        "models": {m: {"scores": copy.deepcopy((scores or {}).get(m, {}))} for m in ids},
    }
    if fallback not in doc["models"]:
        doc["models"][fallback] = {"scores": {}}
    doc.update(over)
    return doc


def evidence(**kwargs: Any) -> ev.Evidence:
    return ev.parse(json.dumps(document(**kwargs)), TODAY)


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc)

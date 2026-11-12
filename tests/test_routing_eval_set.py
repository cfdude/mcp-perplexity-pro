"""The evaluation set of the router (routing-v2 task 3.2): sizes, shapes, the seeded split and
the two frozen hashes.

The set was authored BEFORE the router exists, so nothing can be tuned to the held-out prompts.
Editing a prompt or a ``split`` value turns the hash tests red on purpose: after the first scored
run the files do not change.
"""

import hashlib
import json
from collections import Counter

import pytest
from routing_eval import coverage
from routing_eval import promptset as ps
from routing_eval.split import HELDOUT_PER_CLASS, MAIN_PER_CLASS, assign

from mcp_perplexity_pro.rules import classify, task_class

PROMPTS = ps.load_prompts()
EVAL = ps.evaluation_prompts(PROMPTS)
# The 44 prompts of the labeled set before this change: their tier and mark labels never move
# (SHA-256 of "expected<TAB>mark<TAB>text" lines, taken from commit 4744fc5).
LEGACY_COUNT = 44
LEGACY_TIERS_SHA256 = "9ab9c89835d10e7a93698540e8091d2391b7c59320ce98047c47c321234bf756"


# The classes the coverage gate keeps (acceptance/coverage.md, generated): the harness and these
# tests score only those. An excluded class stays in the prompt file and is still hashed.
KEPT = coverage.kept_classes()


def by(split, task):
    return [p for p in EVAL if p["split"] == split and p["task"] == task]


# --- sizes ------------------------------------------------------------------------------------


def test_the_kept_list_is_a_subset_of_the_three_classes():
    assert set(KEPT) <= set(ps.CLASSES)


@pytest.mark.parametrize("task", ps.CLASSES)
def test_every_class_in_the_file_has_15_main_and_5_heldout_prompts(task):
    # the prompt file keeps all three classes whatever the gate kept (nothing is edited)
    assert len(by("main", task)) == MAIN_PER_CLASS == 15
    assert len(by("heldout", task)) == HELDOUT_PER_CLASS == 5


@pytest.mark.parametrize("task", KEPT)
def test_each_kept_class_has_15_main_and_5_heldout_prompts(task):
    assert len(by("main", task)) == MAIN_PER_CLASS == 15
    assert len(by("heldout", task)) == HELDOUT_PER_CLASS == 5


def test_the_frozen_file_sizes_are_45_main_and_15_heldout_overall():
    counts = Counter(p["split"] for p in EVAL)
    assert counts == {"main": 45, "heldout": 15}
    assert {p["task"] for p in EVAL} == set(ps.CLASSES)


def test_the_scored_sizes_are_15_main_and_5_heldout_per_kept_class():
    scored = [p for p in EVAL if p["task"] in KEPT]
    assert (
        Counter(p["split"] for p in scored)
        == {
            "main": 15 * len(KEPT),
            "heldout": 5 * len(KEPT),
        }
        or not KEPT
    )


@pytest.mark.parametrize("split", ["main", "heldout"])
def test_at_least_half_of_each_subset_is_machine_checkable(split):
    rows = [p for p in EVAL if p["split"] == split]
    checkable = sum(ps.is_machine_checkable(p) for p in rows)
    assert checkable * 2 >= len(rows)
    for task in ps.CLASSES:
        sub = by(split, task)
        assert sum(ps.is_machine_checkable(p) for p in sub) * 2 >= len(sub), (split, task)


def test_ids_are_unique_and_texts_are_unique():
    ids = [p["id"] for p in EVAL]
    assert len(set(ids)) == len(ids)
    texts = [p["text"] for p in PROMPTS]
    assert len(set(texts)) == len(texts)


# --- shapes -----------------------------------------------------------------------------------


@pytest.mark.parametrize("item", EVAL, ids=lambda p: p["id"])
def test_every_evaluation_prompt_has_a_well_formed_eval_block(item):
    assert ps.shape_problems(item) == []
    assert item["split"] in ("main", "heldout") and item["task"] in ps.CLASSES


def test_only_evaluation_prompts_carry_an_eval_and_every_one_has_a_split():
    assert all(("eval" in p) == ("split" in p) for p in PROMPTS)


@pytest.mark.parametrize(
    "block",
    [
        {},
        {"check": {"kind": "exact", "value": "x"}, "rubric": ["a"]},
        {"check": {"kind": "exec", "value": "print(1)"}},
        {"check": {"kind": "exact", "value": ""}},
        {"check": {"kind": "regex", "pattern": "("}},
        {"check": {"kind": "number", "value": "4", "tolerance": 0}},
        {"check": {"kind": "number", "value": 4}},
        {"check": {"kind": "number", "value": 4, "tolerance": -1}},
        {"check": {"kind": "exact", "value": "x", "code": "print(1)"}},
        {"rubric": []},
        {"rubric": ["a", "b", "c", "d", "e", "f"]},
        {"rubric": ["a", ""]},
    ],
)
def test_a_malformed_eval_block_is_reported(block):
    assert ps.shape_problems({"eval": block}) != []


def test_a_five_criterion_rubric_is_the_most_allowed():
    assert ps.shape_problems({"eval": {"rubric": list("abcde")}}) == []


@pytest.mark.parametrize("item", EVAL, ids=lambda p: p["id"])
def test_the_task_label_is_what_the_rules_say_and_the_tier_is_labeled(item):
    assert task_class(item["text"]) == item["task"]
    assert item["expected"] in ("light", "standard", "complex")
    if item["mark"] == "clear":
        assert classify(item["text"]).tier == item["expected"]


# --- the split --------------------------------------------------------------------------------


def test_every_split_value_is_what_the_seeded_rule_assigns():
    ids_by_class = {t: [p["id"] for p in EVAL if p["task"] == t] for t in ps.CLASSES}
    assert {p["id"]: p["split"] for p in EVAL} == assign(ids_by_class)


def test_the_rule_depends_on_ids_only_and_is_stable():
    ids = [f"x{n:02d}" for n in range(20)]
    first = assign({"c": ids})
    assert first == assign({"c": list(reversed(ids))})
    assert sum(v == "heldout" for v in first.values()) == 5


# --- tier labels unchanged --------------------------------------------------------------------


def test_the_tier_labels_of_the_original_44_prompts_are_unchanged():
    legacy = PROMPTS[:LEGACY_COUNT]  # the file keeps them first; later prompts are appended
    assert all("split" not in p for p in legacy)
    lines = "".join(f"{p['expected']}\t{p['mark']}\t{p['text']}\n" for p in legacy)
    assert hashlib.sha256(lines.encode()).hexdigest() == LEGACY_TIERS_SHA256


# --- the two frozen hashes --------------------------------------------------------------------


def test_the_prompt_set_matches_its_frozen_hash():
    assert ps.prompt_set_digest() == ps.recorded(ps.PROMPT_HASH_PATH)


def test_the_heldout_split_matches_its_frozen_hash():
    assert ps.split_digest() == ps.recorded(ps.SPLIT_HASH_PATH)


def test_editing_one_split_value_changes_the_split_digest():
    edited = json.loads(json.dumps(PROMPTS))
    first = next(p for p in edited if "split" in p)
    first["split"] = "main" if first["split"] == "heldout" else "heldout"
    assert ps.split_digest(edited) != ps.split_digest(PROMPTS)


# --- the pilot --------------------------------------------------------------------------------


def test_the_pilot_has_six_prompts_outside_the_set_with_well_formed_checks():
    pilot = json.loads(ps.PILOT_PATH.read_text())
    assert len(pilot) == 6
    texts = {p["text"] for p in PROMPTS}
    for item in pilot:
        assert item["text"] not in texts
        assert ps.shape_problems(item) == [] and task_class(item["text"]) == item["task"]
    assert Counter(p["task"] for p in pilot) == {"coding": 2, "reasoning": 2, "browsing": 2}

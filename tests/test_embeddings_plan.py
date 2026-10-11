"""Task 5.1 (py-embeddings): the pure index planner."""

from mcp_perplexity_pro.embeddings import MAX_BATCH_CHARS, MAX_BATCH_INPUTS, plan_index


def sizes(plan):
    return [len(batch) for batch in plan.batches]


def test_150_one_chunk_items_with_limit_100_make_batches_of_64_and_36_and_leave_50():
    plan = plan_index([["c"]] * 150, 100)
    assert sizes(plan) == [64, 36] and plan.taken_items == 100 and plan.remaining == 50


def test_limit_one_takes_the_whole_first_item_and_remaining_counts_only_the_others():
    plan = plan_index([["a", "b", "c"], ["d"], ["e", "f"]], 1)
    assert plan.taken_items == 1 and sizes(plan) == [3] and plan.remaining == 3


def test_repeated_planning_with_limit_one_terminates():
    pending = [["a"] * 3, ["b"] * 2, ["c"]]
    rounds = 0
    while pending:
        plan = plan_index(pending, 1)
        assert plan.taken_items >= 1
        pending = pending[plan.taken_items :]
        rounds += 1
    assert rounds == 3


def test_a_limit_reached_inside_an_item_still_takes_the_item_whole():
    plan = plan_index([["a"] * 5, ["b"] * 5], 3)
    assert plan.taken_items == 1 and sizes(plan) == [5] and plan.remaining == 5


def test_forty_chunks_of_4000_characters_make_batches_of_25_and_15():
    plan = plan_index([["x" * 4000] * 40], 2048)
    assert sizes(plan) == [25, 15] and plan.remaining == 0
    assert all(sum(len(c.text) for c in batch) <= MAX_BATCH_CHARS for batch in plan.batches)


def test_a_fifty_chunk_item_spans_batches_and_keeps_its_chunk_order():
    plan = plan_index([["y" * 4000] * 50], 256)
    assert sizes(plan) == [25, 25]
    flat = [c for batch in plan.batches for c in batch]
    assert [c.chunk_index for c in flat] == list(range(50)) and {c.item for c in flat} == {0}


def test_no_batch_ever_exceeds_64_inputs_or_the_character_budget():
    items = [["z" * 10] * 50 for _ in range(10)]
    plan = plan_index(items, 2048)
    assert plan.remaining == 0 and plan.taken_items == 10
    assert all(len(b) <= MAX_BATCH_INPUTS for b in plan.batches)
    assert sum(sizes(plan)) == 500


def test_an_empty_plan():
    plan = plan_index([], 256)
    assert plan.batches == [] and plan.taken_items == 0 and plan.remaining == 0

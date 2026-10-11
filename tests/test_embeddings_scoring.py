"""Task 6.1 (py-embeddings): cosine and Hamming scoring, blocking and tie order."""

import math

import numpy as np
import pytest

from mcp_perplexity_pro.embeddings import BLOCK_ROWS, cosine_scores, hamming_scores, top_k


def i8(*values):
    return np.array(values, dtype=np.int8).tobytes()


def matrix(*rows):
    return np.array(rows, dtype=np.int8)


def test_the_spec_cosine_value():
    score = cosine_scores(i8(1, 0), matrix([1, 1]))[0]
    assert score == pytest.approx(math.sqrt(0.5), abs=1e-6)  # about 0.7071


def test_identical_opposite_and_zero_vectors():
    m = matrix([5, -3, 2], [-5, 3, -2], [0, 0, 0])
    got = cosine_scores(i8(5, -3, 2), m)
    assert got[0] == pytest.approx(1.0, abs=1e-6) and got[1] == pytest.approx(-1.0, abs=1e-6)
    assert got[2] == 0.0
    assert cosine_scores(i8(0, 0, 0), m).tolist() == [0.0, 0.0, 0.0]


def test_the_spec_hamming_value_and_extremes():
    q = np.array([0b11110000], dtype=np.uint8).tobytes()
    m = np.array([[0b11000000], [0b11110000], [0b00001111]], dtype=np.uint8)
    got = hamming_scores(q, m, 8)
    assert got.tolist() == [0.75, 1.0, 0.0]


def python_cosine(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return 0.0 if na == 0 or nb == 0 else sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def test_a_vectorized_call_equals_the_row_by_row_python_result():
    rng = np.random.default_rng(7)
    rows = rng.integers(-128, 128, size=(300, 64), dtype=np.int8)
    query = rng.integers(-128, 128, size=64, dtype=np.int8)
    got = cosine_scores(query.tobytes(), rows)
    for i in range(0, 300, 37):
        assert got[i] == pytest.approx(python_cosine(query.tolist(), rows[i].tolist()), abs=1e-5)


def make_rows(n, width=16, seed=3):
    rng = np.random.default_rng(seed)
    data = rng.integers(-128, 128, size=(n, width), dtype=np.int8)
    return [(1000 + i, data[i].tobytes()) for i in range(n)], rng.integers(
        -128, 128, width, dtype=np.int8
    ).tobytes()


def test_blocking_over_5000_rows_equals_the_unblocked_ranking():
    rows, query = make_rows(5000)
    assert len(rows) > 2 * BLOCK_ROWS
    blocked = top_k(query, rows, k=10, encoding="int8", dimensions=16)
    full = cosine_scores(query, np.array([np.frombuffer(v, np.int8) for _, v in rows]))
    order = np.lexsort((np.array([i for i, _ in rows]), -full))[:10]
    assert [i for i, _ in blocked] == [rows[j][0] for j in order]
    assert [s for _, s in blocked] == pytest.approx([float(full[j]) for j in order], abs=1e-6)


def test_equal_scores_are_ordered_by_chunk_id_across_blocks():
    same = i8(3, 4)
    rows = [(i, same) for i in (9, 4, 7, 2, 5000, 1)]
    got = top_k(same, rows, k=4, encoding="int8", dimensions=2)
    assert [i for i, _ in got] == [1, 2, 4, 7]
    many = [(i, same) for i in range(BLOCK_ROWS * 2 + 5, 0, -1)]
    assert [i for i, _ in top_k(same, many, k=3, encoding="int8", dimensions=2)] == [1, 2, 3]


def test_min_score_top_k_and_binary_ranking():
    rows = [(1, i8(1, 0)), (2, i8(1, 1)), (3, i8(-1, 0))]
    assert [i for i, _ in top_k(i8(1, 0), rows, k=5, encoding="int8", dimensions=2)] == [1, 2, 3]
    assert [i for i, _ in top_k(i8(1, 0), rows, k=1, encoding="int8", dimensions=2)] == [1]
    kept = top_k(i8(1, 0), rows, k=5, encoding="int8", dimensions=2, min_score=0.5)
    assert [i for i, _ in kept] == [1, 2]
    packed = [(1, bytes([0b11110000])), (2, bytes([0b11000000])), (3, bytes([0b00001111]))]
    got = top_k(bytes([0b11110000]), packed, k=3, encoding="binary", dimensions=8)
    assert got == [(1, 1.0), (2, 0.75), (3, 0.0)]
    assert top_k(i8(1, 0), [], k=3, encoding="int8", dimensions=2) == []

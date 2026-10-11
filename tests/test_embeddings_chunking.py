"""Task 3.1 (py-embeddings): deterministic chunking, hashing and the shared blank rule."""

import re

from mcp_perplexity_pro.embeddings import chunk_text, is_blank, text_hash


def squash(value):
    return re.sub(r"\s+", "", value)


def test_a_short_text_is_one_chunk():
    assert chunk_text("a" * 100) == (["a" * 100], False)


def test_a_long_text_of_lines_splits_at_line_breaks_and_loses_nothing_but_whitespace():
    text = "\n".join(f"{i:03d}" + "x" * 96 for i in range(90))  # 9000 characters of 100-char lines
    chunks, cut = chunk_text(text)
    assert not cut and len(chunks) == 3
    assert all(len(c) <= 4000 for c in chunks)
    assert all(c.splitlines()[-1].startswith(f"{int(c.splitlines()[-1][:3]):03d}") for c in chunks)
    assert squash("".join(chunks)) == squash(text)


def test_a_blank_line_is_preferred_over_a_line_break():
    paragraph = "p" * 1500
    text = "\n\n".join([paragraph, paragraph, paragraph])  # 4504 characters
    chunks, _ = chunk_text(text)
    assert chunks == [paragraph + "\n\n" + paragraph, paragraph]


def test_unbroken_text_splits_at_the_limit_and_a_space_is_preferred_to_it():
    chunks, cut = chunk_text("x" * 5000)
    assert [len(c) for c in chunks] == [4000, 1000] and not cut
    words, _ = chunk_text(("word " * 1000).strip())  # 4999 characters
    assert all(len(c) <= 4000 and not c.startswith(" ") for c in words)
    assert squash("".join(words)) == squash("word " * 1000)


def test_more_than_fifty_chunks_are_cut_to_fifty_and_reported():
    chunks, cut = chunk_text("y" * (4000 * 51))
    assert len(chunks) == 50 and cut
    chunks, cut = chunk_text("y" * (4000 * 50))
    assert len(chunks) == 50 and not cut


def test_whitespace_only_text_gives_no_chunks_and_chunking_is_deterministic():
    assert chunk_text("  \n\n  ") == ([], False)
    text = "alpha beta\n\n" * 700
    assert chunk_text(text) == chunk_text(text)


def test_the_hash_and_the_blank_rule():
    assert text_hash("a") == text_hash("a") != text_hash("b") and len(text_hash("a")) == 64
    assert is_blank("  \n") and is_blank("") and is_blank(None) and is_blank(5)
    assert not is_blank(" x ")

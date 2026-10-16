"""routing-rules-v1 task 1.1: the scenarios of the ``routing-rules`` spec, and the vocabulary,
question rule and thresholds of design D2 pinned by name."""

import subprocess
import sys

import pytest

from mcp_perplexity_pro import rules
from mcp_perplexity_pro.rules import Classification, classify

SIGNAL_ORDER = ("vocabulary", "length", "questions", "lookup")


def filler(n: int) -> str:
    """Exactly ``n`` characters of plain text with no vocabulary, ending in one question mark."""
    base = "The nightly job reads rows from a table and writes them to a file. "
    return (base * (n // len(base) + 1))[: n - 1] + "?"


# --- the pins of design D2 ------------------------------------------------------------------


def test_the_thresholds_are_pinned():
    assert rules.LENGTH_COMPLEX == 1200
    assert rules.QUESTIONS_COMPLEX == 3
    assert rules.VOCABULARY_COMPLEX == 2
    assert rules.LIGHT_MAX_LENGTH == 120
    assert rules.LIGHT_MAX_QUESTIONS == 1
    assert rules.REASON_MAX_LENGTH == 120


def test_the_analysis_vocabulary_is_pinned_by_family():
    assert rules.ANALYSIS_GROUPS == (
        ("compare", "comparison"),
        ("evaluate", "evaluation"),
        ("trade-off", "trade-offs", "tradeoff", "tradeoffs"),
        ("pros and cons",),
        ("step by step",),
        ("root cause",),
        ("architecture",),
        ("in depth",),
        ("analyze", "analyse", "analysis"),
        ("critique",),
        ("derive",),
        ("prove",),
        ("design",),
        ("implications",),
    )


def test_the_lookup_openings_are_pinned():
    assert rules.LOOKUP_OPENINGS == (
        "what is",
        "what are",
        "who is",
        "who was",
        "when did",
        "when is",
        "where is",
        "how many",
        "how much",
        "define",
        "latest",
        "current",
        "price of",
    )


@pytest.mark.parametrize("group", rules.ANALYSIS_GROUPS, ids=lambda g: g[0])
def test_two_vocabulary_groups_make_a_text_complex_for_every_group(group):
    # each group, paired with one fixed other group, reaches the threshold; dropping the
    # group from the vocabulary would turn this red
    other = "critique" if group[0] != "critique" else "derive"
    result = classify(f"Please {group[0]} this and {other} it")
    assert result.tier == "complex" and result.signals == ("vocabulary",)


@pytest.mark.parametrize("group", rules.ANALYSIS_GROUPS, ids=lambda g: g[0])
def test_every_form_of_one_family_counts_once(group):
    text = "Please " + " and ".join(group)
    assert classify(text).tier != "complex"  # one family, however many forms


def test_the_vocabulary_matches_whole_words_without_regard_to_case():
    assert classify("COMPARE these and Evaluate them").signals == ("vocabulary",)
    assert classify("precompare and evaluated things").tier == "standard"  # no whole word
    assert classify("A Trade-Off, a pros   and\ncons list").signals == ("vocabulary",)


# --- the spec scenarios ----------------------------------------------------------------------


def test_same_text_same_result_in_one_process_and_across_hash_seeds():
    text = "Compare two libraries and evaluate their trade-offs?"
    assert classify(text) == classify(text)
    code = (
        "from mcp_perplexity_pro.rules import classify\n"
        f"print(classify({text!r}))\n"  # a dataclass repr: tier, reason, classifier, signals
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code],  # not -I: isolated mode ignores PYTHONHASHSEED
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("1", "2", "3", "random")
    }
    assert len(outputs) == 1 and "complex" in outputs.pop()


def test_the_classification_shape():
    result = classify("What is the latest stable Python release?")
    assert isinstance(result, Classification)
    assert result.classifier == "rules"
    assert isinstance(result.signals, tuple)
    with pytest.raises(AttributeError):  # frozen
        result.tier = "complex"  # type: ignore[misc]


def test_the_reason_holds_no_prompt_text():
    secret = "hunter2-AKIAIOSFODNN7EXAMPLE"
    for text in (
        f"My password is {secret}. Compare it and evaluate it?",
        f"{secret} " * 300,
        f"What is {secret}?",
        f"{secret}? {secret}? {secret}?",
    ):
        reason = classify(text).reason
        assert "hunter2" not in reason and "AKIA" not in reason
        assert reason.isascii() and len(reason) <= rules.REASON_MAX_LENGTH


def test_the_reason_names_signals_and_counts():
    assert classify(filler(1500)).reason == "1500 chars"
    assert classify("Compare these, evaluate them and critique it").reason == "3 analysis terms"
    assert classify("Is it? Why? When?").reason == "3 questions"
    assert classify("define idempotent").reason == "short lookup"
    assert classify("Tell me about otters").reason == "no signals"
    both = classify("Compare and evaluate " + filler(1300))
    assert both.reason == "2 analysis terms, 1321 chars"


def test_signals_come_in_the_fixed_order():
    text = "Compare and evaluate this. Why? How? When?\n" + filler(1300)
    assert classify(text).signals == ("vocabulary", "length", "questions")
    assert list(classify(text).signals) == [s for s in SIGNAL_ORDER if s in classify(text).signals]


def test_two_analysis_words():
    result = classify("Compare these two libraries and evaluate their trade-offs")
    assert result.tier == "complex" and result.signals == ("vocabulary",)


def test_one_analysis_word_alone_is_not_enough():
    assert classify("Please compare these two libraries for me").tier == "standard"


def test_a_long_text():
    result = classify(filler(1500))
    assert result.tier == "complex" and result.signals == ("length",)


def test_the_length_boundary_and_trimming():
    assert classify(filler(1199)).tier == "standard"
    assert classify(filler(1200)).tier == "complex"
    assert classify("   " + filler(1199) + "   \n").tier == "standard"  # trimmed first


def test_several_questions():
    result = classify("Which one? Can I change it? Who signs?")
    assert result.tier == "complex" and result.signals == ("questions",)
    assert classify("Which one? Can I change it?").tier == "standard"


def test_numbered_items_count_like_questions():
    three = classify("Cover:\n1. one\n2. two\n3. three")
    assert three.tier == "complex" and three.signals == ("questions",)
    assert classify("Cover:\n1) one\n  2) two\n3. three").tier == "complex"
    assert classify("Cover:\n1. one\n2. two").tier == "standard"
    assert classify("The year was 1999. It ended.").tier == "standard"  # not at a line start
    assert classify("Why?\n1. one\n2. two").tier == "complex"  # a question plus two items


def test_a_version_or_year_at_a_line_start_is_not_a_numbered_item():
    notes = "3.12 release notes?\n3.11 release notes\n3.10 release notes"
    assert classify(notes).tier == "standard"
    assert classify("1.5 times faster?\n2.5 times slower\n3.5 times more").tier == "standard"
    assert classify("Cover:\n1.   one\n2.\ttwo\n3.  three").tier == "complex"  # spacing is fine
    assert (
        classify("Cover:\n\u0661. one\n\u0662. two\n\u0663. three").tier == "standard"
    )  # not ASCII


def test_a_question_mark_inside_a_url_is_not_a_question():
    text = "Is https://example.com/a?x=1 the same as https://example.com/a?x=2&y=3 for a crawler?"
    assert classify(text).signals == ()
    urls_only = "See https://e.com/a?x=1 and https://e.com/b?y=2 and https://e.com/c?z=3"
    assert classify(urls_only).tier == "standard"


def test_fullwidth_and_arabic_question_marks_count_anywhere():
    assert classify("これは何？どうして？いつ？").tier == "complex"
    assert classify("ما هذا؟ لماذا؟ متى؟").tier == "complex"
    assert classify("what?x?y?").tier == "standard"  # ASCII needs whitespace or the end


def test_a_lookup():
    result = classify("What is the latest stable Python release?")
    assert result.tier == "light" and result.signals == ("lookup",)


def test_every_lookup_opening_is_light():
    for opening in rules.LOOKUP_OPENINGS:
        assert classify(f"{opening.upper()} python").tier == "light", opening


def test_a_lookup_without_a_question_mark():
    assert classify("define idempotent").tier == "light"


def test_a_lookup_needs_the_opening_at_the_start_and_a_whole_word():
    assert classify("Tell me what is the latest release").tier == "standard"
    assert classify("Latestly speaking, ok").tier == "standard"
    assert classify("  \n What is a monad?").tier == "light"


def test_a_lookup_that_is_too_long_or_asks_too_much_is_standard():
    assert classify("What is " + "x" * 112).tier == "light"  # exactly 120
    assert classify("What is " + "x" * 113).tier == "standard"  # 121
    assert classify("What is a monad? What is a functor?").tier == "standard"  # two questions


def test_a_lookup_with_a_complexity_signal_is_complex():
    assert classify("What is a monad? Why? How? When?").tier == "complex"
    assert classify("What is the architecture and design of it?").tier == "complex"


def test_a_short_text_that_is_not_a_lookup():
    result = classify("Explain why the design failed")
    assert result.tier == "standard" and result.signals == ()


def test_an_ordinary_question():
    text = ("Which payment provider is easiest to add to a small website, " * 6)[:299] + "?"
    result = classify(text)
    assert result.tier == "standard" and len(text) == 300


def test_text_the_vocabulary_cannot_read():
    result = classify("東京で一番おいしいラーメン屋さんはどこにあるか教えてもらえますか？")
    assert result.tier == "standard" and result.signals == () and result.reason == "no signals"


def test_empty_and_blank_text_never_raise():
    for text in ("", "   ", "\n\t"):
        assert classify(text).tier == "standard"


# --- no side effects: the module is pure -------------------------------------------------------


def test_the_module_imports_no_settings_network_database_or_fastmcp():
    code = (
        "import sys\n"
        "for name in ('fastmcp', 'mcp', 'sqlalchemy', 'httpx2', 'httpx', 'pydantic_settings'):\n"
        "    sys.modules[name] = None\n"  # a blocked import raises ImportError
        "import mcp_perplexity_pro.rules\n"
        "assert 'mcp_perplexity_pro.settings' not in sys.modules\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

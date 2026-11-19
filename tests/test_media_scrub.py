"""scrub_media inside redact_text (media-attachments: error text is scrubbed of media)."""

import time

import pytest

from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.redaction import REDACTED, redact_text, scrub_media

MARK = "[media removed]"
MIXED = ("AbCdEfGh0123456789" * 20)[:300]  # upper, lower, digits, no slashes


def test_a_data_uri_body_is_replaced_and_the_text_after_it_kept():
    text = 'sent "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==" and then more text'
    out = scrub_media(text)
    assert "iVBOR" not in out
    assert out.startswith('sent "data:' + MARK + '"')
    assert out.endswith(" and then more text")


def test_upper_case_data_scheme_and_not_inside_a_word():
    assert "iVBOR" not in scrub_media("DATA:image/png;base64,iVBORw0KGgo=")
    assert scrub_media("metadata:abc") == "metadata:abc"
    assert scrub_media("see data: next") == "see data: next"


def test_a_bare_mixed_base64_run_is_replaced():
    out = scrub_media(f"echo {MIXED} end")
    assert MIXED[:40] not in out
    assert out == f"echo {MARK} end"


def test_look_alikes_survive():
    assert scrub_media("r" * 500) == "r" * 500
    digest = "a3f5" * 16
    assert scrub_media(digest) == digest
    path = "/" + "/".join(["abcdef0123"] * 12)
    assert len(path) >= 120 and scrub_media(path) == path
    assert (
        scrub_media("A1" * 100 + "_" + "b" * 10) == "A1" * 100 + "_" + "b" * 10
    )  # 200 chars: no lower


def test_the_alphabet_excludes_underscore_and_dash():
    run = ("AbCd0123" * 40)[:150] + "_" + ("EfGh4567" * 40)[:150]
    assert scrub_media(run) == run  # neither half reaches 200 characters


def test_slash_heavy_runs_are_kept():
    run = ("Ab1/" * 80)[:300]  # a path-like run: slashes * 16 > length
    assert scrub_media(run) == run


def test_a_run_straddling_the_echo_cut_is_gone_before_truncation():
    err = PerplexityError("upstream_failure", "bad request: " + MIXED)
    assert MARK in str(err)
    assert MIXED[:30] not in str(err)
    assert MIXED[:30] not in str(err)[:60]


def test_redact_text_scrubs_media_before_key_removal_and_truncation():
    out = redact_text(f"x {MIXED} pplx-" + "a" * 30)
    assert MARK in out and REDACTED in out
    assert MIXED[:30] not in out


def test_perplexity_error_message_and_api_message_are_scrubbed():
    err = PerplexityError(
        "invalid_request",
        "400: " + MIXED,
        status=400,
        api_message="quoted " + MIXED,
    )
    assert MARK in str(err) and MARK in (err.api_message or "")
    assert MIXED[:30] not in str(err) and MIXED[:30] not in (err.api_message or "")


def test_scrub_is_linear_on_hostile_input():
    hostile = ("A" * 199 + "!") * 5000 + "Ab1" * 400_000
    start = time.monotonic()
    redact_text(hostile)
    assert time.monotonic() - start < 3
    start = time.monotonic()
    redact_text("data:" + "=" * 1_000_000)
    assert time.monotonic() - start < 3


@pytest.mark.parametrize("text", ["", "plain text", "https://example.com/a.png"])
def test_ordinary_text_is_untouched(text):
    assert scrub_media(text) == text


def test_failure_text_redacts_the_whole_text_then_cuts():
    """A base64 run that straddles the 2000-character cut used to survive as a fragment."""
    from mcp_perplexity_pro.usage import _failure_text

    try:
        raise RuntimeError(MIXED + " " + "y" * 1985)
    except RuntimeError as exc:
        text = _failure_text(exc, ())
    assert MIXED[-6:] not in text
    assert len(text) <= 2000


def test_a_validation_error_on_attachments_never_quotes_the_value():
    """ErrorContractMiddleware drops the input_value of an `attachments` error (the tool has no
    such parameter yet, so the error is synthetic: the text pydantic renders for a list item)."""
    from types import SimpleNamespace

    from fastmcp.exceptions import ValidationError

    from mcp_perplexity_pro.server import ErrorContractMiddleware

    secret_path = "/Users/rob/private-" + "x" * 20 + ".png"
    text = (
        "1 validation error for call[perplexity_ask]\n"
        "attachments.0\n"
        f"  Input should be a valid string [type=string_type, input_value={secret_path!r}, "
        "input_type=str]\n"
        "    For further information visit https://errors.pydantic.dev/2.x/v/string_type"
    )
    ctx = SimpleNamespace(message=SimpleNamespace(name="perplexity_ask"))
    result = ErrorContractMiddleware()._classify(ctx, ValidationError(text))
    shown = result.content[0].text
    assert "attachments.0" in shown and "private-" not in shown
    assert result.structured_content["category"] == "invalid_request"

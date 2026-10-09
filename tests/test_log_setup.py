"""Logging goes to stderr only, with the key and key-shaped tokens redacted everywhere."""

import logging

import pytest

from mcp_perplexity_pro.log_setup import (
    REDACTED,
    RedactingFilter,
    configure_logging,
    log_payload,
    redact_text,
)

KEY = "test-dummy-api-key"
TOKEN = "pplx-" + "Ab3_" * 10  # key-shaped, deliberately not the configured key


@pytest.fixture(autouse=True)
def restore_logging():
    """configure_logging touches global logger state; put it back after every test."""
    root = logging.getLogger()
    fastmcp = logging.getLogger("fastmcp")
    saved = (list(root.handlers), root.level, list(fastmcp.handlers), fastmcp.propagate)
    yield
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    fastmcp.handlers[:] = saved[2]
    fastmcp.propagate = saved[3]


def test_message_with_key_and_token_is_redacted(capsys):
    configure_logging("INFO", [KEY])
    logging.getLogger("t").info("calling with %s and %s", KEY, TOKEN)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert KEY not in captured.err
    assert TOKEN not in captured.err
    assert captured.err.count(REDACTED) == 2


def test_literal_message_is_redacted(capsys):
    configure_logging("INFO", [KEY])
    logging.getLogger("t").warning(f"header was Bearer {KEY} / {TOKEN}")
    captured = capsys.readouterr()
    assert KEY not in captured.err
    assert TOKEN not in captured.err


def test_mapping_args_are_redacted(capsys):
    configure_logging("INFO", [KEY])
    logging.getLogger("t").info("%(k)s %(t)s", {"k": KEY, "t": TOKEN})
    captured = capsys.readouterr()
    assert KEY not in captured.err
    assert TOKEN not in captured.err


def test_exception_text_and_traceback_are_redacted(capsys):
    configure_logging("INFO", [KEY])
    try:
        raise ValueError(f"upstream echoed {KEY} and {TOKEN}")
    except ValueError:
        logging.getLogger("t").exception("call failed")
    captured = capsys.readouterr()
    assert "call failed" in captured.err
    assert "ValueError" in captured.err
    assert KEY not in captured.err
    assert TOKEN not in captured.err


def test_extra_string_attributes_are_redacted(capsys):
    configure_logging("INFO", [KEY])
    logging.getLogger("t").info("msg", extra={"detail": f"k={KEY}"})
    handler = next(h for h in logging.getLogger().handlers if h.get_name() == "mcp_perplexity_pro")
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    record.detail = f"k={KEY}"
    assert handler.filter(record)
    assert KEY not in record.detail
    assert KEY not in capsys.readouterr().err


def test_fastmcp_logger_output_is_redacted_and_goes_to_stderr(capsys):
    configure_logging("INFO", [KEY])
    try:
        raise RuntimeError(f"tool blew up with {KEY}")
    except RuntimeError:
        logging.getLogger("fastmcp.server").error("Error calling tool 'x'", exc_info=True)
    captured = capsys.readouterr()
    assert "Error calling tool 'x'" in captured.err
    assert KEY not in captured.err
    assert captured.out == ""


def test_token_shape_is_redacted_without_any_configured_key(capsys):
    configure_logging("INFO")
    logging.getLogger("t").info("got %s", TOKEN)
    assert TOKEN not in capsys.readouterr().err


def test_short_or_empty_secrets_do_not_mangle_messages():
    f = RedactingFilter(["", KEY])
    assert redact_text("plain message", ["", KEY]) == "plain message"
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "plain %s", ("x",), None)
    assert f.filter(record)
    assert record.getMessage() == "plain x"


def test_level_is_applied_and_messages_below_it_are_dropped(capsys):
    configure_logging("WARNING", [KEY])
    logging.getLogger("t").info("quiet")
    logging.getLogger("t").warning("loud")
    err = capsys.readouterr().err
    assert "quiet" not in err
    assert "loud" in err


def test_configure_twice_installs_one_handler():
    configure_logging("INFO", [KEY])
    configure_logging("DEBUG", [KEY])
    ours = [h for h in logging.getLogger().handlers if h.get_name() == "mcp_perplexity_pro"]
    assert len(ours) == 1
    assert logging.getLogger().level == logging.DEBUG


def test_payload_is_not_logged_at_the_default_level(capsys):
    configure_logging("INFO", [KEY])
    log_payload(logging.getLogger("t"), "request body", {"prompt": "tell me a secret"})
    assert capsys.readouterr().err == ""


def test_payload_at_debug_is_still_redacted(capsys):
    configure_logging("DEBUG", [KEY])
    log_payload(logging.getLogger("t"), "request body", {"prompt": f"use {KEY}"})
    err = capsys.readouterr().err
    assert "request body" in err
    assert KEY not in err

"""Logging goes to stderr only, with the key and key-shaped tokens redacted everywhere."""

import logging

import pytest

from mcp_perplexity_pro.log_setup import (
    REDACTED,
    RedactingFilter,
    configure_logging,
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


def test_a_database_errors_bound_values_are_not_written(capsys):
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import SQLAlchemyError

    configure_logging("INFO", [KEY])
    stored = "STORED-" + "ANSWER-TEXT"  # built here so no source line in a traceback holds it
    try:
        with create_engine("sqlite://").begin() as conn:
            conn.execute(text("INSERT INTO nope VALUES (:v)"), {"v": stored})
    except SQLAlchemyError:
        logging.getLogger("fastmcp.server.server").exception("Error calling tool 'x'")
    err = capsys.readouterr().err
    assert "no such table" in err and "Error calling tool" in err
    assert stored not in err and "parameters: omitted" in err


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


def test_a_record_with_many_unclosed_parameter_openers_scrubs_in_linear_time():
    import time

    f = RedactingFilter()
    secret = "STORED-ANSWER-TEXT"
    text = "[parameters: " * 23_000 + secret  # ~300 KB, no opener ever closes
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, text, None, None)
    start = time.perf_counter()
    assert f.filter(record)
    assert time.perf_counter() - start < 1.0
    assert secret not in record.msg  # an unclosed block is redacted to the end of the record
    assert "parameters: omitted" in record.msg


def test_a_record_without_a_parameter_block_passes_through_unchanged():
    f = RedactingFilter()
    text = "plain error with [brackets] and (parens)\nsecond line " * 3
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, text, None, None)
    assert f.filter(record)
    assert record.msg == text


def test_a_closed_parameter_block_is_stripped_and_the_background_line_kept():
    f = RedactingFilter()
    text = (
        "(sqlite3.OperationalError) no such table: nope\n"
        "[SQL: INSERT INTO nope VALUES (?)]\n"
        "[parameters: ('SECRET-VALUE [x] with ] brackets',)]\n"
        "(Background on this error at: https://sqlalche.me/e/20/e3q8)"
    )
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, text, None, None)
    assert f.filter(record)
    assert "SECRET-VALUE" not in record.msg
    assert "[parameters: omitted]\n(Background on this error" in record.msg
    assert "no such table: nope" in record.msg

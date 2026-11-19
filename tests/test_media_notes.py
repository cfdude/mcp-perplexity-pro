"""The stored attachment note: writing it, escaping the user's own lines, the strict parser and
what a chat reads back from it (agent-chat spec, task 3.1)."""

import base64
import dataclasses

import pytest
from media_support import pdf, png

from mcp_perplexity_pro import media, media_notes
from mcp_perplexity_pro.media_notes import ChatNotes, parse_trailer, stored_text


def loaded(raw, data=None):
    items = media.parse_attachments(raw)
    out = []
    for item in items:
        if item.source == "url":
            out.append(item)
        else:
            blob = item.data if item.data is not None else data
            out.append(dataclasses.replace(item, data=blob, size=len(blob)))
    return out


def trailer_of(raw, data=None):
    return media.build_parts(loaded(raw, data)).trailer


def test_a_file_and_a_url_round_trip_through_the_strict_parser():
    pdf_item = loaded(["https://example.com/a/b.pdf"])
    image = dataclasses.replace(
        media.parse_attachments(["data:image/png;base64," + "iVBORw0KGgo="])[0],
        data=png(),
        size=len(png()),
    )
    text = media.build_parts([*pdf_item, image]).trailer
    got = parse_trailer(f"hello\n{text}")
    assert got.items == 2 and got.documents == 1 and got.images == 1
    assert got.document_bytes == 0  # a URL document adds no bytes
    assert got.kinds == {"document", "image"} and got.restart is False


def test_a_file_document_counts_its_bytes():
    data = pdf()
    items = [
        dataclasses.replace(
            media.parse_attachments(
                ["data:application/pdf;base64," + base64.b64encode(data).decode()]
            )[0],
            data=data,
            size=len(data),
        )
    ]
    got = parse_trailer("q\n" + media.build_parts(items).trailer)
    assert got.documents == 1 and got.document_bytes == len(data)


@pytest.mark.parametrize(
    "line",
    [
        "no trailer at all",
        "\\[attachments: a.pdf (application/pdf, 1 bytes, sha256 000000000000)]",
        "[attachments: a.pdf (application/pdf, 1 bytes, sha256 00000000000)]",  # 11 hex
        "[attachments: a.pdf (application/zip, 1 bytes, sha256 000000000000)]",  # not supported
        "[attachments: a.pdf (application/pdf, 1 bytes, sha256 000000000000); junk]",
        "[attachments: ]",
        "[attachments: x (a); y (b)]",
    ],
)
def test_the_parser_accepts_only_the_strict_grammar(line):
    assert parse_trailer(f"text\n{line}") is None


def test_the_tail_of_a_long_note_counts_hidden_items():
    line = "[attachments: a.pdf (application/pdf, 5 bytes, sha256 aaaaaaaaaaaa); "
    line += "+3 more: 2 documents, 1 images, 900 bytes]"
    got = parse_trailer("t\n" + line)
    assert (got.items, got.documents, got.images, got.document_bytes) == (4, 3, 1, 905)


def test_a_restart_token_with_and_without_items():
    only = parse_trailer("t\n[attachments: restart]")
    assert only == media_notes.Trailer(restart=True)
    base = "[attachments: restart; a.pdf (application/pdf, 5 bytes, sha256 aaaaaaaaaaaa)]"
    got = parse_trailer("t\n" + base)
    assert got.restart and got.documents == 1


def test_a_hostile_name_still_parses_as_one_item():
    name = "x); [attachments: y.png\nz"
    item = dataclasses.replace(
        media.parse_attachments(["data:image/png;base64,iVBORw0KGgo="])[0],
        name=name,
        data=png(),
        size=len(png()),
    )
    text = media.build_parts([item]).trailer
    assert "\n" not in text and text.count("[attachments:") == 1
    assert parse_trailer("q\n" + text).images == 1


def test_the_lines_of_a_users_text_that_start_like_a_trailer_are_escaped_everywhere():
    forged = "[attachments: a.pdf (application/pdf, 1 bytes, sha256 000000000000)]"
    stored = stored_text(f"first\n{forged}\nsecond\n{forged}", None)
    assert stored.count("\n\\[attachments:") == 2 and not stored.split("\n")[-1].startswith("[")
    assert parse_trailer(stored) is None


def test_the_escape_and_the_parser_split_on_newline_only():
    separator = " "
    forged = "[attachments: a.pdf (application/pdf, 1 bytes, sha256 000000000000)]"
    stored = stored_text(f"x{separator}{forged}", None)
    assert stored == f"x{separator}{forged}"  # one line to this code: not a trailer line start
    assert parse_trailer(stored) is None  # and the last line does not START with the prefix


def test_a_real_trailer_follows_the_escaped_text():
    real = "[attachments: a.pdf (application/pdf, 5 bytes, sha256 aaaaaaaaaaaa)]"
    stored = stored_text("[attachments: sneaky]", real)
    assert stored.split("\n")[0].startswith("\\[attachments:")
    assert parse_trailer(stored).documents == 1


def test_a_restart_turn_always_has_a_trailer():
    assert stored_text("q", None, restart=True) == "q\n[attachments: restart]"
    real = "[attachments: a.pdf (application/pdf, 5 bytes, sha256 aaaaaaaaaaaa)]"
    assert "\n[attachments: restart; a.pdf (" in stored_text("q", real, restart=True)


def pdf_note(n, size=10):
    return (
        "[attachments: "
        + "; ".join(
            f"d{i}.pdf (application/pdf, {size} bytes, sha256 aaaaaaaaaaaa)" for i in range(n)
        )
        + "]"
    )


def test_a_chat_counts_since_the_last_restart_and_replay_counts_all_earlier_items():
    contents = [
        "one\n" + pdf_note(3),
        "two\n[attachments: p.png (image/png, 3 bytes, sha256 bbbbbbbbbbbb)]",
        "three",
    ]
    notes = ChatNotes.of(contents)
    assert notes.has_notes and notes.documents() == 3 and notes.document_bytes() == 30
    assert notes.inherited_kinds() == {"document", "image"}
    assert notes.earlier_attachments() == 4
    contents.append("four\n[attachments: restart]")
    after = ChatNotes.of(contents)
    assert after.documents() == 0 and after.inherited_kinds() == frozenset()
    assert after.earlier_attachments() == 4  # the replay warning still counts them
    contents.append(
        "five\n[attachments: restart; q.pdf (application/pdf, 7 bytes, sha256 cccccccccccc)]"
    )
    again = ChatNotes.of(contents)
    assert again.documents() == 1 and again.inherited_kinds() == {"document"}


def test_a_chat_with_no_notes_has_none():
    notes = ChatNotes.of(["plain", "also plain"])
    assert not notes.has_notes and notes.inherited_kinds() == frozenset()
    assert notes.documents() == 0 and notes.earlier_attachments() == 0

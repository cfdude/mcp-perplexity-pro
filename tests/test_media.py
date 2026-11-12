"""media.py: the grammar, kinds, signatures, URL rules, limits, parts and notes of attachments
(media-attachments, agent-chat note grammar). Pure: no file is read here (1.3 owns the read)."""

import base64
import dataclasses
import hashlib
import time

import media_support as ms
import pytest

from mcp_perplexity_pro import media
from mcp_perplexity_pro.errors import PerplexityError


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


PNG = ms.png()
PDF = ms.pdf()


def png_uri(data: bytes = PNG, extra: str = "") -> str:
    return f"data:image/png{extra};base64,{b64(data)}"


def refused(raw, *needles, index=0):
    with pytest.raises(PerplexityError) as info:
        media.parse_attachments(raw if isinstance(raw, list) else [raw])
    assert info.value.category == "invalid_request"
    text = str(info.value)
    for needle in needles:
        assert needle in text, text
    return text


# --- the list ------------------------------------------------------------------------------


def test_three_forms_are_classified_and_nothing_is_read():
    items = media.parse_attachments(
        ["/Users/rob/shot.png", "https://example.com/report.pdf", png_uri()]
    )
    assert [i.source for i in items] == ["path", "url", "data"]
    assert [i.kind for i in items] == ["image", "document", "image"]
    assert items[0].data is None  # a path is not read by the parser
    assert items[2].data == PNG


def test_empty_list_is_no_attachments():
    assert media.parse_attachments([]) == []
    assert media.parse_attachments(None) == []


def test_eleven_items_fail_naming_the_limit():
    refused(["/a/b.png"] * 11, "attachments", "10")


@pytest.mark.parametrize("bad", [[""], ["   "], [1], [None], "a.png", {"a": 1}])
def test_blank_and_non_string_items_and_other_shapes_fail(bad):
    refused(bad, "attachments")


def test_the_position_is_named():
    text = refused(["/a/b.png", "  "], "attachments[1]")
    assert "attachments[0]" not in text


# --- the grammar ---------------------------------------------------------------------------


def test_relative_path_is_refused():
    refused("shot.png", "attachments[0]", "absolute", "~/")


def test_prefix_form_on_a_url_sets_the_type():
    [item] = media.parse_attachments(["application/pdf::https://example.com/download?id=7"])
    assert (item.kind, item.media_type) == ("document", "application/pdf")
    assert item.url == "https://example.com/download?id=7"


def test_upper_case_schemes():
    items = media.parse_attachments(
        ["HTTPS://example.com/a.png", "DATA:image/png;base64," + b64(PNG)]
    )
    assert [i.source for i in items] == ["url", "data"]


def test_prefixed_relative_path_fails_for_the_path_not_the_prefix():
    text = refused("image/png::shot.png", "absolute")
    assert "prefix" not in text


def test_prefix_on_a_path_must_equal_the_derived_type():
    refused("image/jpeg::/a/b.png", "attachments[0]", "image/png")
    [item] = media.parse_attachments(["image/png::/a/b.png"])
    assert item.media_type == "image/png"


def test_prefix_on_inline_data_must_equal_the_derived_type():
    refused("application/pdf::" + png_uri(), "attachments[0]")


def test_tilde_prefix_expands_the_home_directory_only():
    [item] = media.parse_attachments(["~/shot.png"])
    assert item.path.endswith("/shot.png") and item.path.startswith("/")
    assert "~" not in item.path
    refused("~rob/shot.png", "absolute")


# --- kinds and types -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "kind", "mt"),
    [
        ("/a/x.PNG", "image", "image/png"),
        ("/a/x.jpg", "image", "image/jpeg"),
        ("/a/x.jpeg", "image", "image/jpeg"),
        ("/a/x.webp", "image", "image/webp"),
        ("/a/x.gif", "image", "image/gif"),
        ("/a/x.pdf", "document", "application/pdf"),
        ("/a/x.doc", "document", "application/msword"),
        (
            "/a/x.docx",
            "document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("/a/x.txt", "document", "text/plain"),
        ("/a/x.rtf", "document", "application/rtf"),
    ],
)
def test_kind_and_type_come_from_the_extension(path, kind, mt):
    [item] = media.parse_attachments([path])
    assert (item.kind, item.media_type) == (kind, mt)


def test_unlisted_type_lists_the_supported_ones():
    refused("/a/x.xyz", "attachments[0]", "png", "pdf")


def test_underivable_url_type_shows_the_prefix_form():
    refused("https://example.com/download?id=7", "application/pdf::https://")


@pytest.mark.parametrize("path", ["/a/call.mp3", "/a/call.wav", "/a/clip.mp4", "/a/clip.mov"])
def test_audio_and_video_are_refused(path):
    text = refused(path, "attachments[0]")
    assert "audio" in text or "video" in text


def test_audio_data_uri_is_refused():
    refused("data:audio/wav;base64," + b64(ms.wav()), "attachments[0]", "audio")


def test_data_uri_parameters_are_dropped():
    [item] = media.parse_attachments(["data:text/plain;charset=utf-8;base64,aGk="])
    assert item.media_type == "text/plain" and item.data == b"hi"


def test_text_rtf_is_normalised():
    [item] = media.parse_attachments(["data:text/rtf;base64," + b64(ms.rtf())])
    assert item.media_type == "application/rtf"


# --- signatures ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mt", "data", "ok"),
    [
        ("image/png", PNG, True),
        ("image/png", PDF, False),
        ("image/jpeg", b"\xff\xd8\xff\xe0abc", True),
        ("image/jpeg", PNG, False),
        ("image/webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ", True),
        ("image/webp", b"RIFF\x00\x00\x00\x00WAVEfmt ", False),
        ("image/gif", b"GIF89a....", True),
        ("image/gif", b"GIF87a....", True),
        ("image/gif", b"GIF90a....", False),
        ("application/pdf", PDF, True),
        ("application/pdf", PNG, False),
        ("application/msword", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1....", True),
        ("application/msword", PDF, False),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ms.docx(),
            True,
        ),
        ("application/rtf", ms.rtf(), True),
        ("application/rtf", b"plain text", False),
        ("text/plain", "héllo".encode(), True),
        ("text/plain", b"a\x00b", False),
        ("text/plain", b"\xff\xfe\x00", False),
    ],
)
def test_signatures(mt, data, ok):
    assert media.check_bytes(mt, data) is ok


def test_inline_bytes_that_do_not_match_the_declared_type_fail():
    refused("data:image/png;base64," + b64(PDF), "attachments[0]", "image/png")


# --- inline data ---------------------------------------------------------------------------


def test_bad_base64_names_the_item_and_does_not_echo_it():
    junk = "!" * 5000
    text = refused(f"data:image/png;base64,{junk}", "attachments[0]", "image/png")
    assert "!!!!" not in text


def test_data_without_base64_marker_is_refused():
    refused("data:text/plain,hello", "attachments[0]", "base64")


def test_oversized_inline_data_points_to_a_path_or_url():
    big = ms.png(700, 700)  # a few KiB compressed is not enough: use a raw size instead
    data = PNG + b"\x00" * (2 * 1024 * 1024)
    assert len(data) > media.MAX_INLINE_BYTES
    text = refused("data:image/png;base64," + b64(data), "attachments[0]", "1 MiB", "path")
    assert big  # silence the helper use
    assert "AAAA" not in text


def test_inline_size_check_runs_before_decoding(monkeypatch):
    called = []
    real = base64.b64decode
    monkeypatch.setattr(base64, "b64decode", lambda *a, **k: (called.append(1), real(*a, **k))[1])
    payload = "A" * (3 * 1024 * 1024)
    refused("data:image/png;base64," + payload, "1 MiB")
    assert not called


# --- URLs ----------------------------------------------------------------------------------


def test_credentials_are_refused_and_not_echoed():
    text = refused("https://user:secret@example.com/a.pdf", "attachments[0]")
    assert "secret" not in text


def test_http_is_refused():
    refused("http://example.com/a.png", "attachments[0]", "HTTPS")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a\\b.png",
        "https://example.com/a\n.png",
        "https://example.com/a\x00.png",
        "https://example.com/a.png#frag",
        "https://example.com:8443/a.png",
        "https://[::1]/a.png",
        "https://bücher.example/a.pdf",
        "https://exa mple.com/a.png",
        "https:///a.png",
    ],
)
def test_url_shape_is_restricted(url):
    refused(url, "attachments[0]")


def test_non_ascii_host_says_punycode():
    refused("https://bücher.example/a.pdf", "punycode")


def test_port_443_and_long_urls():
    media.parse_attachments(["https://example.com:443/a.png"])
    refused("https://example.com/" + "a" * 2040 + ".png", "2048")


def test_url_is_passed_through_untouched():
    url = "https://example.com/a.pdf?X-Amz-Signature=abc123&b=%20c"
    [item] = media.parse_attachments([url])
    assert item.url == url and item.data is None


def test_url_document_filename_comes_from_the_path_or_the_type():
    [a] = media.parse_attachments(["https://example.com/report.pdf"])
    [b] = media.parse_attachments(["application/pdf::https://example.com/download?id=7"])
    [c] = media.parse_attachments(
        [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            "::https://example.com/get"
        ]
    )
    assert (a.name, b.name, c.name) == ("report.pdf", "document.pdf", "document.docx")


# --- limits --------------------------------------------------------------------------------


def with_data(item, data):
    return dataclasses.replace(item, data=data, size=len(data))


def test_per_file_and_total_limits(monkeypatch):
    [item] = media.parse_attachments(["/a/x.pdf"])
    over = dataclasses.replace(item, size=media.MAX_FILE_BYTES + 1)
    with pytest.raises(PerplexityError, match=r"attachments\[0\].*20 MiB"):
        media.check_sizes([over])
    a = dataclasses.replace(item, size=17 * 1024 * 1024)
    with pytest.raises(PerplexityError, match=r"attachments.*32 MiB"):
        media.check_sizes([a, a])
    media.check_sizes([dataclasses.replace(item, size=1024)])


def test_body_size_is_computed_not_built(monkeypatch):
    [item] = media.parse_attachments(["/a/x.pdf"])
    item = dataclasses.replace(item, size=3000)
    est = media.body_size([item], "hello")
    assert est >= 4 * 1000 + 5
    monkeypatch.setattr(media, "MAX_BODY_BYTES", est - 1)
    with pytest.raises(PerplexityError, match="attachments.*64 MiB|body"):
        media.check_body_size([item], "hello")
    monkeypatch.setattr(media, "MAX_BODY_BYTES", est)
    media.check_body_size([item], "hello")


def test_lowered_constants_reach_the_backstop_without_building_anything(monkeypatch):
    monkeypatch.setattr(media, "MAX_FILE_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(media, "MAX_TOTAL_BYTES", 200 * 1024 * 1024)
    [item] = media.parse_attachments(["/a/x.pdf"])
    big = dataclasses.replace(item, size=49 * 1024 * 1024)
    media.check_sizes([big])
    with pytest.raises(PerplexityError, match="64 MiB"):
        media.check_body_size([big, dataclasses.replace(big)], "q")


# --- parts and notes -----------------------------------------------------------------------


def test_parts_follow_the_order_and_shapes():
    items = media.parse_attachments(
        ["/a/shot.png", "https://example.com/report.pdf", "/a/notes.pdf", "https://e.com/p.jpg"]
    )
    items[0] = with_data(items[0], PNG)
    items[2] = with_data(items[2], PDF)
    built = media.build_parts(items)
    p = built.parts
    assert p[0] == {
        "type": "input_image",
        "image_url": "data:image/png;base64," + b64(PNG),
    }
    assert p[1] == {
        "type": "input_file",
        "file_url": "https://example.com/report.pdf",
        "filename": "report.pdf",
    }
    assert p[2] == {"type": "input_file", "filename": "notes.pdf", "file_data": b64(PDF)}
    assert p[3] == {"type": "input_image", "image_url": "https://e.com/p.jpg"}


def test_document_from_inline_data_is_plain_base64_with_a_typed_filename():
    [item] = media.parse_attachments(["data:application/pdf;base64," + b64(PDF)])
    [part] = media.build_parts([item]).parts
    assert part == {"type": "input_file", "filename": "document.pdf", "file_data": b64(PDF)}
    assert "file_url" not in part


def test_filename_rules():
    [item] = media.parse_attachments(["/a/Report.PDF"])
    assert item.name == "Report.pdf"
    long = "/a/" + "é" * 200 + ".pdf"
    [item] = media.parse_attachments([long])
    assert item.name == "document.pdf"
    [item] = media.parse_attachments(["/a/we\x07ird.pdf"])
    assert item.name == "document.pdf"


def test_a_path_item_without_bytes_cannot_be_built():
    [item] = media.parse_attachments(["/a/x.png"])
    with pytest.raises(ValueError):
        media.build_parts([item])


def sha12(b):
    return hashlib.sha256(b).hexdigest()[:12]


def test_notes_for_a_file_and_a_signed_url():
    items = media.parse_attachments(
        ["/Users/rob/shot.png", "https://example.com/files/ab12token/a.pdf?X-Amz-Signature=abc"]
    )
    items[0] = with_data(items[0], PNG)
    built = media.build_parts(items)
    assert built.notes[0] == f"shot.png (image/png, {len(PNG)} bytes, sha256 {sha12(PNG)})"
    h = hashlib.sha256(b"example.com/files/ab12token/a.pdf").hexdigest()[:12]
    assert built.notes[1] == f"example.com (application/pdf, url sha256 {h})"
    assert built.trailer == "[attachments: " + "; ".join(built.notes) + "]"
    assert "ab12token" not in built.trailer and "X-Amz" not in built.trailer


def test_hostile_names_are_sanitized_to_60_characters():
    name = "x); [attachments: y" + "z" * 80
    [item] = media.parse_attachments(["/a/" + name.replace("/", "_") + ".png"])
    item = with_data(item, PNG)
    [note] = media.build_parts([item]).notes
    shown = note.split(" (image/png")[0]
    assert len(shown) <= 60
    assert not any(c in shown for c in ";()[]\n")


def test_a_long_note_keeps_its_counts():
    docx = ms.docx()
    items = []
    for i in range(10):
        [it] = media.parse_attachments([f"/a/{'n' * 100}{i}.docx"])
        items.append(with_data(it, docx))
    built = media.build_parts(items)
    assert len(built.trailer) <= 1500
    assert built.trailer.startswith("[attachments: ")
    shown = built.trailer.count("sha256")
    hidden = 10 - shown
    assert 0 < hidden < 10
    assert built.trailer.endswith(
        f"+{hidden} more: {hidden} documents, 0 images, {hidden * len(docx)} bytes]"
    )


def test_inline_names_and_the_stored_trailer_has_no_bytes():
    [item] = media.parse_attachments([png_uri()])
    built = media.build_parts([item])
    assert b64(PNG)[:20] not in built.trailer
    assert built.notes[0].startswith("inline.png (image/png, ")


# --- the grammar of no attachments, and the validation error text ---------------------------


def test_drop_attachment_values_from_a_validation_text():
    text = (
        "1 validation error for call[perplexity_ask]\n"
        "attachments.0\n"
        "  Input should be a valid string [type=string_type, input_value=12345, input_type=int]\n"
        "    For further information visit https://errors.pydantic.dev/2.x/v/string_type\n"
        "query\n"
        "  Field required [type=missing, input_value={'a': 1}, input_type=dict]\n"
    )
    out = media.drop_attachment_input_values(text)
    assert "12345" not in out and "attachments.0" in out
    assert "input_value={'a': 1}" in out  # other fields keep theirs


def test_drop_handles_a_value_that_contains_the_marker():
    text = (
        "attachments\n  Input should be a valid list "
        "[type=list_type, input_value='x, input_type=y', input_type=str]\n"
    )
    out = media.drop_attachment_input_values(text)
    assert "x, input_type=y" not in out


def test_parsing_is_linear_on_a_hostile_data_uri():
    hostile = "data:image/png;base64," + "A" * 900_000 + "!"
    start = time.monotonic()
    with pytest.raises(PerplexityError):
        media.parse_attachments([hostile])
    assert time.monotonic() - start < 2

"""media-inputs probe fixtures (task 1.1) and the generated media they were captured with."""

import io
import json
import struct
import zipfile
import zlib

import media_support
import pytest
from fixture_support import FIXTURE_DIR


def _load(name):
    body = json.loads((FIXTURE_DIR / f"{name}.json").read_text())
    meta = json.loads((FIXTURE_DIR / f"{name}.meta.json").read_text())
    return body, meta


def _text(body):
    return json.dumps(body.get("output"))


# --- the generated media -------------------------------------------------------------------


def test_png_is_a_valid_48_by_48_png():
    data = media_support.png()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (48, 48)
    # the IDAT chunk inflates to height rows of 1 filter byte + width * 3 bytes
    idat = data[data.index(b"IDAT") + 4 : data.index(b"IEND") - 8]
    assert len(zlib.decompress(idat)) == 48 * (1 + 48 * 3)


def test_pdf_has_magic_and_the_text():
    data = media_support.pdf("hello MANGO")
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    assert b"(hello MANGO)" in data


def test_docx_is_a_zip_with_the_text():
    with zipfile.ZipFile(io.BytesIO(media_support.docx("KIWI here"))) as z:
        assert "word/document.xml" in z.namelist()
        assert b"KIWI here" in z.read("word/document.xml")


def test_rtf_and_wav_magic():
    assert media_support.rtf().startswith(b"{\\rtf1")
    assert media_support.wav()[:4] == b"RIFF"


def test_doc_bytes_is_a_legacy_word_file_or_none():
    data = media_support.doc_bytes()
    if data is None:
        pytest.skip("textutil is not installed")
    assert data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # the OLE2 signature of a DOC


# --- the captured fixtures ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "word"),
    [
        ("agent_image_inline", "red"),
        ("agent_document_inline", "mango"),
        ("agent_document_rtf", "kiwi"),
        ("agent_document_docx", "kiwi"),
    ],
)
def test_accepted_kinds_answer_from_the_attachment(name, word):
    body, meta = _load(name)
    assert meta["http_status"] == 200
    assert body["status"] in {"completed", "incomplete"}
    assert word in _text(body).lower()
    assert body["usage"]["input_tokens"] > 0


def test_document_by_https_url_is_fetched_by_the_provider():
    body, meta = _load("agent_document_url")
    assert meta["http_status"] == 200
    assert meta["request"]["input"][0]["content"][1]["file_url"].startswith("https://")
    assert body["status"] in {"completed", "incomplete"}


def test_image_to_a_model_that_cannot_read_images_is_the_generic_400():
    body, meta = _load("agent_image_unsupported_model_400")
    assert meta["http_status"] == 400
    assert body["error"]["message"] == "invalid request"


def test_document_to_a_route_that_refuses_documents_is_a_named_400():
    body, meta = _load("agent_document_unsupported_route_400")
    assert meta["http_status"] == 400
    assert "does not support this document type or source" in body["error"]["message"]


def test_bad_extension_is_a_named_400():
    body, meta = _load("agent_document_bad_extension_400")
    assert meta["http_status"] == 400
    assert "filename extension does not match document media type" in body["error"]["message"]


def test_audio_part_is_an_invalid_type_400():
    body, meta = _load("agent_audio_invalid_type_400")
    assert meta["http_status"] == 400
    assert 'invalid type "input_audio"' in body["error"]["message"]


def test_a_model_refusal_is_a_200_with_a_failed_run():
    body, meta = _load("agent_document_failed_refusal")
    assert meta["http_status"] == 200
    assert body["status"] == "failed"
    assert body["error"]["code"] == "refusal"
    assert not body.get("usage")


def test_the_file_survives_two_continuation_hops():
    body, meta = _load("agent_chat_document_chained")
    assert len(body["turns"]) == 3 and len(meta["requests"]) == 3
    assert "previous_response_id" in meta["requests"][1]
    assert "previous_response_id" in meta["requests"][2]
    assert "mango" in _text(body["turns"][1]).lower()
    assert "mango" in _text(body["turns"][2]).lower()


def test_no_attachment_bytes_are_stored_in_a_fixture():
    for path in FIXTURE_DIR.glob("agent_*.json"):
        assert "base64," not in path.read_text() or path.name.endswith(".meta.json"), path.name
    for name in ("agent_image_inline", "agent_document_inline"):
        _, meta = _load(name)
        assert len(json.dumps(meta)) < 4000, "the request in a sidecar keeps no attachment bytes"

"""The two fixed attachments of an input probe: a 48 by 48 red PNG and a one-line PDF.

Pure and built from the standard library (no file, no binary blob in the repository); the same
bytes the 2026-10-30 sweep sent, so a probe asks the question the baseline answered."""

import base64
import functools
import struct
import zlib

IMAGE_PROMPT = "What colour is this image? One word."
DOCUMENT_PROMPT = "What is the secret word in the document? One word."
DOCUMENT_TEXT = "The secret word is MANGO"


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = struct.pack(">I", len(data)) + kind + data
        return body + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _pdf(text: str) -> bytes:
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (
        len(objs) + 1,
        xref,
    )


@functools.cache
def image_part() -> dict[str, str]:
    data = base64.b64encode(_png(48, 48, (255, 0, 0))).decode()
    return {"type": "input_image", "image_url": f"data:image/png;base64,{data}"}


@functools.cache
def document_part() -> dict[str, str]:
    data = base64.b64encode(_pdf(DOCUMENT_TEXT)).decode()
    return {"type": "input_file", "filename": "doc.pdf", "file_data": data}


def probe_input_body(model: str, kind: str, max_output_tokens: int) -> dict:
    """The request of one input probe: one user message of the fixed prompt and the fixed
    attachment of ``kind``, ``store`` false, no tools."""
    if kind == "image":
        prompt, part = IMAGE_PROMPT, image_part()
    elif kind == "document":
        prompt, part = DOCUMENT_PROMPT, document_part()
    else:
        raise ValueError(f"unknown input kind {kind!r}")
    return {
        "model": model,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}, dict(part)],
            }
        ],
        "store": False,
        "max_output_tokens": max_output_tokens,
    }

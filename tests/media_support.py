"""Generated media for tests and live captures: no binary blobs are committed.

``png`` builds a solid-colour PNG, ``pdf`` a one-line text PDF, ``wav`` a silent WAV (the audio
case, which the API refuses as an input kind), ``docx`` and ``rtf`` one-line documents. A legacy
``.doc`` needs a converter, so ``doc_bytes`` uses macOS ``textutil`` and returns ``None`` when it
is missing.
"""

import base64
import io
import shutil
import struct
import subprocess
import tempfile
import wave
import zipfile
import zlib
from pathlib import Path


def png(width: int = 48, height: int = 48, rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
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


def pdf(text: str = "The secret word is MANGO") -> bytes:
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


def wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 800)
    return buf.getvalue()


def rtf(text: str = "The secret word is KIWI") -> bytes:
    # the shape textutil writes: a header, a font table and a paragraph (a bare `{\\rtf1 text}` was
    # accepted by the API on 2026-11-11 but its text was not read: the model answered "Please")
    return (
        "{\\rtf1\\ansi\\ansicpg1252\\deff0\n{\\fonttbl\\f0\\fswiss Helvetica;}\n"
        "\\pard\\f0\\fs24 " + text + "\\par\n}"
    ).encode()


def docx(text: str = "The secret word is KIWI") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.'
            'openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="'
            'application/xml"/><Override PartName="/word/document.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
            'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://'
            'schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.'
            'openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
            f"{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buf.getvalue()


def doc_bytes(text: str = "The secret word is KIWI") -> bytes | None:
    """A legacy Word file made by macOS ``textutil``; ``None`` where it is not installed."""
    tool = shutil.which("textutil")
    if tool is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "k.txt"
        src.write_text(text)
        subprocess.run([tool, "-convert", "doc", str(src)], check=True, capture_output=True)
        return (Path(tmp) / "k.doc").read_bytes()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()

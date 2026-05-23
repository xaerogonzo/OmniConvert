"""Shared pytest fixtures for the OmniConvert suite.

Fixtures are *generated* rather than committed so they can't drift from the
libraries that produce them. Nothing here touches Tk — every test in this suite
runs headless.
"""

import struct
import sys
import zlib
from pathlib import Path
from queue import Queue

import pytest

# main.py does the same for the app; tests need it before importing omniconvert.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def write_png(path: Path, width: int = 8, height: int = 8,
              rgb: tuple[int, int, int] = (200, 30, 30)) -> Path:
    """Write a minimal valid RGB PNG without depending on Pillow's encoder."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


@pytest.fixture
def log_q() -> Queue:
    """The queue the pipeline posts progress strings to."""
    return Queue()


def drain(q: Queue) -> list[str]:
    """Return every message currently queued, oldest first."""
    out = []
    while not q.empty():
        out.append(q.get())
    return out


@pytest.fixture
def sample_docx(tmp_path: Path) -> Path:
    """A DOCX with a heading, body text, one embedded PNG and a 2x2 table.

    The stem deliberately contains a space: image references have to survive
    URL-encoding through markdown, weasyprint-style base URLs and pandoc's
    --resource-path, and a space is what breaks naive implementations.
    """
    docx = pytest.importorskip("docx", reason="python-docx is a dev dependency")

    png = write_png(tmp_path / "embedded.png")
    doc = docx.Document()
    doc.add_heading("Sample Heading", level=1)
    doc.add_paragraph("Paragraph before the image.")
    doc.add_picture(str(png))
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "A"
    table.cell(0, 1).text = "B"
    table.cell(1, 0).text = "1"
    table.cell(1, 1).text = "2"

    out = tmp_path / "Sample Doc.docx"
    doc.save(str(out))
    return out

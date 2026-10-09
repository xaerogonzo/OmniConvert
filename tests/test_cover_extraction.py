"""Cover selection from a DOCX.

The rule used to be "largest file in word/media/ over 5 KB". Byte size is a
poor proxy for "is this a cover": a flat or heavily-compressed full-page image
can sit well under 5 KB and be skipped, while a noisy 64x64 icon sails past the
floor and gets chosen. Selection is now by image dimensions.
"""

import io
import zipfile

import pytest

from conftest import drain, write_png
from omniconvert.converters import assets

docx_mod = pytest.importorskip("docx", reason="python-docx is a dev dependency")
Image = pytest.importorskip("PIL.Image", reason="Pillow is required")


def build_docx(path, images):
    """A DOCX embedding `images` (paths) in order."""
    d = docx_mod.Document()
    d.add_paragraph("body text")
    for img in images:
        d.add_picture(str(img))
    d.save(str(path))
    return path


def media_sizes(docx_path):
    with zipfile.ZipFile(str(docx_path)) as zf:
        return {
            i.filename.rsplit("/", 1)[-1]: i.file_size
            for i in zf.infolist()
            if i.filename.startswith("word/media/")
        }


class TestSelection:
    def test_a_flat_full_page_image_is_found(self, tmp_path, log_q):
        """The regression the byte floor caused.

        A 600x800 solid-colour cover compresses to well under 5 KB, so the old
        rule discarded it and reported "No media files found".
        """
        cover = write_png(tmp_path / "cover.png", 600, 800)          # flat, tiny
        src = build_docx(tmp_path / "Flat.docx", [cover])
        assert media_sizes(src)["image1.png"] < 5 * 1024, "fixture must be under the old floor"

        out = tmp_path / "out.png"
        assert assets.extract_cover(src, log_q, out=out) == out
        with Image.open(out) as img:
            assert img.size == (600, 800)

    def test_the_page_sized_image_beats_a_heavier_icon(self, tmp_path, log_q):
        """A noisy icon can outweigh a cover in bytes while being obviously
        not a cover."""
        icon = write_png(tmp_path / "icon.png", 64, 64, noisy=True)   # heavy, tiny
        cover = write_png(tmp_path / "cover.png", 700, 900)           # light, huge
        src = build_docx(tmp_path / "Mixed.docx", [icon, cover])

        sizes = media_sizes(src)
        assert max(sizes.values()) == sizes["image1.png"], (
            "fixture must have the ICON as the largest file, or it proves nothing"
        )

        out = tmp_path / "out.png"
        assets.extract_cover(src, log_q, out=out)
        with Image.open(out) as img:
            assert img.size == (700, 900), "chose the heavier icon over the cover"

    def test_largest_page_sized_image_wins(self, tmp_path, log_q):
        small = write_png(tmp_path / "a.png", 300, 300)
        big = write_png(tmp_path / "b.png", 500, 650)
        src = build_docx(tmp_path / "Two.docx", [small, big])
        out = tmp_path / "out.png"
        assets.extract_cover(src, log_q, out=out)
        with Image.open(out) as img:
            assert img.size == (500, 650)


class TestFallback:
    def test_an_icon_only_document_still_yields_something(self, tmp_path, log_q):
        """Better a small image than none - the old rule would have taken it."""
        icon = write_png(tmp_path / "icon.png", 90, 90, noisy=True)
        src = build_docx(tmp_path / "IconOnly.docx", [icon])
        out = tmp_path / "out.png"
        assert assets.extract_cover(src, log_q, out=out) == out
        with Image.open(out) as img:
            assert img.size == (90, 90)

    def test_the_fallback_says_so(self, tmp_path, log_q):
        icon = write_png(tmp_path / "icon.png", 90, 90, noisy=True)
        src = build_docx(tmp_path / "IconOnly.docx", [icon])
        assets.extract_cover(src, log_q, out=tmp_path / "out.png")
        assert any("may not be a real cover" in m for m in drain(log_q))

    def test_a_real_cover_is_not_flagged(self, tmp_path, log_q):
        cover = write_png(tmp_path / "cover.png", 600, 800)
        src = build_docx(tmp_path / "Real.docx", [cover])
        assets.extract_cover(src, log_q, out=tmp_path / "out.png")
        assert not any("may not be a real cover" in m for m in drain(log_q))


class TestDegradation:
    def test_a_document_with_no_media_reports_it(self, tmp_path, log_q):
        d = docx_mod.Document()
        d.add_paragraph("text only")
        src = tmp_path / "Bare.docx"
        d.save(str(src))
        assert assets.extract_cover(src, log_q, out=tmp_path / "out.png") is None
        assert any("No media files" in m for m in drain(log_q))

    def test_undecodable_media_is_skipped_not_fatal(self, tmp_path, log_q):
        """Word stores vector art as EMF/WMF, which Pillow cannot open."""
        cover = write_png(tmp_path / "cover.png", 600, 800)
        src = build_docx(tmp_path / "WithEmf.docx", [cover])

        # Splice a bogus "image" in that Pillow will refuse, larger than the real one.
        patched = tmp_path / "Patched.docx"
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(patched, "w") as zout:
            for item in zin.infolist():
                zout.writestr(item, zin.read(item.filename))
            zout.writestr("word/media/image9.emf", b"\x01\x00\x00\x00" + b"\xff" * 50_000)

        out = tmp_path / "out.png"
        assert assets.extract_cover(patched, log_q, out=out) == out
        with Image.open(out) as img:
            assert img.size == (600, 800), "the undecodable blob must not win"

    def test_extraction_never_raises_on_a_corrupt_file(self, tmp_path, log_q):
        bad = tmp_path / "NotReally.docx"
        bad.write_bytes(b"this is not a zip")
        assert assets.extract_cover(bad, log_q, out=tmp_path / "out.png") is None

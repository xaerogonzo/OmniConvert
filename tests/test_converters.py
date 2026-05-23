"""Behavioural tests for the two converter paths this release changed.

`_from_docx` moved off markitdown's default handler onto mammoth-direct so that
DOCX images land on disk instead of being inlined as base64. `_to_pdf` moved off
weasyprint (which needs GTK/Pango DLLs that cannot be bundled into the Nuitka
exe) onto PyMuPDF's Story renderer.
"""

import pytest

from conftest import drain, write_png
from omniconvert.converters import from_markdown, to_markdown

pymupdf = pytest.importorskip("pymupdf")


class TestDocxToMarkdown:
    """The regression this release exists to fix."""

    def test_images_are_written_as_real_files(self, sample_docx, tmp_path, log_q):
        md_out = tmp_path / "Sample Doc_docx.md"
        img_dir = tmp_path / "Sample Doc_docx_img"
        to_markdown.convert(sample_docx, md_out, img_dir, log_q)

        assert img_dir.is_dir()
        assert [p.name for p in sorted(img_dir.iterdir())] == ["img_001.png"]
        assert (img_dir / "img_001.png").stat().st_size > 0

    def test_no_base64_data_uri_survives(self, sample_docx, tmp_path, log_q):
        """mammoth's default handler inlines images; ours must not."""
        md_out = tmp_path / "Sample Doc_docx.md"
        to_markdown.convert(sample_docx, md_out, tmp_path / "Sample Doc_docx_img", log_q)
        assert "data:image" not in md_out.read_text(encoding="utf-8")

    def test_reference_includes_the_img_folder_and_is_url_safe(
        self, sample_docx, tmp_path, log_q
    ):
        """The reference must carry the folder name (weasyprint/pandoc resolve it
        against the .md's parent) and must percent-encode the space in the stem."""
        md_out = tmp_path / "Sample Doc_docx.md"
        img_dir = tmp_path / "Sample Doc_docx_img"
        to_markdown.convert(sample_docx, md_out, img_dir, log_q)
        md = md_out.read_text(encoding="utf-8")
        assert "Sample%20Doc_docx_img/img_001.png" in md
        assert "Sample Doc_docx_img/img_001.png" not in md  # raw space would break

    def test_headings_and_tables_survive(self, sample_docx, tmp_path, log_q):
        md_out = tmp_path / "Sample Doc_docx.md"
        to_markdown.convert(sample_docx, md_out, tmp_path / "img", log_q)
        md = md_out.read_text(encoding="utf-8")
        assert "# Sample Heading" in md
        assert "| A | B |" in md

    def test_image_count_is_logged(self, sample_docx, tmp_path, log_q):
        to_markdown.convert(sample_docx, tmp_path / "o.md", tmp_path / "o_img", log_q)
        assert any("1 image(s)" in m for m in drain(log_q))


class TestMarkdownToPdf:
    def _render(self, tmp_path, log_q, md_text, *, strict_tables=True, img=None):
        md = tmp_path / "doc_md.md"
        md.write_text(md_text, encoding="utf-8")
        if img is not None:
            img_dir = tmp_path / "doc_md_img"
            img_dir.mkdir(exist_ok=True)
            write_png(img_dir / img)
        out = tmp_path / "out.pdf"
        from_markdown.convert(md, tmp_path / "doc_md_img", None, "pdf", out,
                              log_q, strict_tables=strict_tables)
        return out

    def test_renders_without_any_system_libraries(self, tmp_path, log_q):
        out = self._render(tmp_path, log_q, "# Title\n\nSome body text.\n")
        assert out.exists() and out.stat().st_size > 0
        with pymupdf.open(str(out)) as doc:
            assert "Title" in doc[0].get_text()

    def test_relative_image_reference_is_embedded(self, tmp_path, log_q):
        out = self._render(
            tmp_path, log_q,
            "# Pic\n\n![](doc_md_img/shot.png)\n", img="shot.png",
        )
        with pymupdf.open(str(out)) as doc:
            assert len(doc[0].get_images(full=True)) == 1

    def test_strict_table_grid_draws_borders(self, tmp_path, log_q):
        table = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"
        with pymupdf.open(str(self._render(tmp_path, log_q, table,
                                           strict_tables=True))) as doc:
            ruled = len(doc[0].get_drawings())
        assert ruled > 0

    def test_strict_table_grid_off_draws_none(self, tmp_path, log_q):
        table = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"
        with pymupdf.open(str(self._render(tmp_path, log_q, table,
                                           strict_tables=False))) as doc:
            assert len(doc[0].get_drawings()) == 0

    def test_long_document_paginates(self, tmp_path, log_q):
        body = "\n\n".join(f"## Section {i}\n\n" + ("filler text " * 80)
                           for i in range(25))
        with pymupdf.open(str(self._render(tmp_path, log_q, body))) as doc:
            assert doc.page_count > 1

    def test_oversized_image_does_not_hang(self, tmp_path, log_q):
        """A picture far wider than the text column must scale, not loop forever."""
        img_dir = tmp_path / "doc_md_img"
        img_dir.mkdir()
        write_png(img_dir / "wide.png", width=2400, height=300)
        md = tmp_path / "doc_md.md"
        md.write_text("![](doc_md_img/wide.png)\n\nAfter.\n", encoding="utf-8")
        out = tmp_path / "out.pdf"
        from_markdown.convert(md, img_dir, None, "pdf", out, log_q)
        with pymupdf.open(str(out)) as doc:
            assert doc.page_count < 10

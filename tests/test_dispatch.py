"""Format dispatch in to_markdown.convert / from_markdown.convert.

The helpers are monkeypatched so these stay fast and dependency-free: the point
is that each extension routes to the right parser/generator and that unknown
formats raise rather than silently producing nothing.
"""

import pytest

from omniconvert.converters import from_markdown, to_markdown


class TestToMarkdownDispatch:
    @pytest.mark.parametrize(
        "suffix, helper",
        [(".pdf", "_from_pdf"), (".docx", "_from_docx"), (".epub", "_from_epub")],
    )
    def test_routes_to_the_right_parser(self, suffix, helper, tmp_path, log_q,
                                        monkeypatch):
        called = {}
        monkeypatch.setattr(
            to_markdown, helper,
            lambda *a, **k: called.update(hit=True), raising=True,
        )
        to_markdown.convert(
            tmp_path / f"x{suffix}", tmp_path / "x.md", tmp_path / "x_img", log_q
        )
        assert called == {"hit": True}

    def test_txt_routes_to_txt_reader(self, tmp_path, log_q, monkeypatch):
        called = {}
        monkeypatch.setattr(to_markdown, "_from_txt",
                            lambda *a, **k: called.update(hit=True))
        to_markdown.convert(tmp_path / "x.txt", tmp_path / "x.md",
                            tmp_path / "x_img", log_q)
        assert called == {"hit": True}

    def test_extension_match_is_case_insensitive(self, tmp_path, log_q, monkeypatch):
        called = {}
        monkeypatch.setattr(to_markdown, "_from_pdf",
                            lambda *a, **k: called.update(hit=True))
        to_markdown.convert(tmp_path / "x.PDF", tmp_path / "x.md",
                            tmp_path / "x_img", log_q)
        assert called == {"hit": True}

    def test_md_is_copied_through_unchanged(self, tmp_path, log_q):
        src = tmp_path / "in.md"
        src.write_text("# Hello\n\nbody\n", encoding="utf-8")
        dest = tmp_path / "out.md"
        to_markdown.convert(src, dest, tmp_path / "img", log_q)
        assert dest.read_text(encoding="utf-8") == "# Hello\n\nbody\n"

    def test_unsupported_input_raises(self, tmp_path, log_q):
        with pytest.raises(ValueError, match="Unsupported input format"):
            to_markdown.convert(tmp_path / "x.rtf", tmp_path / "x.md",
                                tmp_path / "x_img", log_q)


class TestFromMarkdownDispatch:
    def test_pdf_routes_to_the_pymupdf_renderer(self, tmp_path, log_q, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            from_markdown, "_to_pdf",
            lambda md, out, q, strict_tables=True, **kw: seen.update(strict=strict_tables),
        )
        from_markdown.convert(tmp_path / "x.md", tmp_path / "img", None,
                              "pdf", tmp_path / "out.pdf", log_q, strict_tables=False)
        assert seen == {"strict": False}

    @pytest.mark.parametrize(
        "fmt, pandoc_fmt", [("docx", "docx"), ("epub", "epub3"), ("txt", "plain")]
    )
    def test_pandoc_targets_use_the_right_writer(self, fmt, pandoc_fmt, tmp_path,
                                                 log_q, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            from_markdown, "_to_pandoc",
            lambda md, img, pf, out, q, **kw: seen.update(fmt=pf, kw=kw),
        )
        from_markdown.convert(tmp_path / "x.md", tmp_path / "img", None,
                              fmt, tmp_path / f"out.{fmt}", log_q)
        assert seen["fmt"] == pandoc_fmt

    def test_epub_receives_the_cover(self, tmp_path, log_q, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            from_markdown, "_to_pandoc",
            lambda md, img, pf, out, q, **kw: seen.update(kw),
        )
        cover = tmp_path / "c.png"
        from_markdown.convert(tmp_path / "x.md", tmp_path / "img", cover,
                              "epub", tmp_path / "out.epub", log_q)
        assert seen["cover_path"] == cover

    def test_md_target_copies_the_hub_file(self, tmp_path, log_q):
        md = tmp_path / "hub.md"
        md.write_text("hub content", encoding="utf-8")
        out = tmp_path / "final.md"
        from_markdown.convert(md, tmp_path / "img", None, "md", out, log_q)
        assert out.read_text(encoding="utf-8") == "hub content"

    def test_unsupported_output_raises(self, tmp_path, log_q):
        with pytest.raises(ValueError, match="Unsupported output format"):
            from_markdown.convert(tmp_path / "x.md", tmp_path / "img", None,
                                  "rtf", tmp_path / "out.rtf", log_q)

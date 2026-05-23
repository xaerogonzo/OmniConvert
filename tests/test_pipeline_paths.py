"""Path-safety and collision-guard helpers in converters/pipeline.py.

These are the pure functions the rest of the pipeline leans on. They have no
I/O beyond `Path.exists`, so they are cheap to cover exhaustively.
"""

import pytest

from omniconvert.converters.pipeline import (
    _intermediate_paths,
    _unique_path,
    sanitize_stem,
)


class TestSanitizeStem:
    def test_colon_becomes_hyphen(self):
        assert sanitize_stem("My Book: Final") == "My Book- Final"

    def test_whitespace_runs_collapse(self):
        assert sanitize_stem("too    many   spaces") == "too many spaces"

    def test_leading_and_trailing_dots_and_spaces_stripped(self):
        assert sanitize_stem("  .hidden.  ") == "hidden"

    @pytest.mark.parametrize(
        "name", ["CON", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9"]
    )
    def test_reserved_windows_names_are_prefixed(self, name):
        assert sanitize_stem(name) == "_" + name

    @pytest.mark.parametrize("name", ["con", "Nul", "cOm3"])
    def test_reserved_match_is_case_insensitive(self, name):
        assert sanitize_stem(name) == "_" + name

    @pytest.mark.parametrize("name", ["CONSOLE", "COM", "COM10", "LPT0", "README"])
    def test_non_reserved_lookalikes_are_untouched(self, name):
        assert sanitize_stem(name) == name

    def test_ordinary_name_is_unchanged(self):
        assert sanitize_stem("Annual Report 2026") == "Annual Report 2026"


class TestUniquePath:
    def test_free_path_returned_as_is(self, tmp_path):
        p = tmp_path / "Draft.docx"
        assert _unique_path(p) == p

    def test_first_collision_gets_suffix_1(self, tmp_path):
        p = tmp_path / "Draft.docx"
        p.touch()
        assert _unique_path(p).name == "Draft (1).docx"

    def test_walks_past_consecutive_collisions(self, tmp_path):
        (tmp_path / "Draft.docx").touch()
        (tmp_path / "Draft (1).docx").touch()
        (tmp_path / "Draft (2).docx").touch()
        assert _unique_path(tmp_path / "Draft.docx").name == "Draft (3).docx"

    def test_suffix_is_preserved(self, tmp_path):
        p = tmp_path / "Report.tar.gz"
        p.touch()
        assert _unique_path(p).name == "Report.tar (1).gz"


class TestIntermediatePaths:
    def test_stem_is_suffixed_with_source_extension(self, tmp_path):
        stem, ext, md, img, cover = _intermediate_paths(tmp_path / "Draft.pdf")
        assert (stem, ext) == ("Draft", "pdf")
        assert md.name == "Draft_pdf.md"
        assert img.name == "Draft_pdf_img"
        assert cover.name == "Draft_pdf_cover.png"

    def test_same_stem_different_formats_do_not_collide(self, tmp_path):
        """The v0.2.0 collision guard: Draft.pdf and Draft.docx share a folder."""
        _, _, md_a, img_a, cov_a = _intermediate_paths(tmp_path / "Draft.pdf")
        _, _, md_b, img_b, cov_b = _intermediate_paths(tmp_path / "Draft.docx")
        assert md_a != md_b and img_a != img_b and cov_a != cov_b

    def test_uppercase_extension_is_normalised(self, tmp_path):
        _, ext, md, _, _ = _intermediate_paths(tmp_path / "Draft.PDF")
        assert ext == "pdf"
        assert md.name == "Draft_pdf.md"

    def test_stem_is_sanitised(self, tmp_path):
        stem, _, md, _, _ = _intermediate_paths(tmp_path / "Book: One.epub")
        assert stem == "Book- One"
        assert md.name == "Book- One_epub.md"

    def test_artifacts_land_beside_the_source(self, tmp_path):
        nested = tmp_path / "deep" / "folder"
        nested.mkdir(parents=True)
        _, _, md, img, cover = _intermediate_paths(nested / "Draft.pdf")
        assert md.parent == img.parent == cover.parent == nested

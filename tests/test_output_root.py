"""`dest_dir` as the artifact root, stem claiming, and intermediate cleanup.

The rules under test here exist because the image-reference contract has been
broken twice already: markdown resolves `![](Book_pdf_img/x.png)` against its own
parent, so the artifact set has to stay a coherent sibling group no matter where
it is rooted or how names collide.
"""

import shutil
from pathlib import Path

import pytest

from conftest import drain, write_png
from omniconvert.converters import pipeline
from omniconvert.converters.pipeline import _intermediate_paths, _run_single

pymupdf = pytest.importorskip("pymupdf")


class TestArtifactRoot:
    def test_default_is_beside_the_source(self, tmp_path):
        """No destination means pre-v0.4.0 behaviour, unchanged."""
        src = tmp_path / "sub" / "Draft.pdf"
        src.parent.mkdir()
        _, _, md, img, cover = _intermediate_paths(src)
        assert md.parent == img.parent == cover.parent == src.parent

    def test_destination_is_the_root_for_every_artifact(self, tmp_path):
        """C1: the markdown, images and cover all move, not just the output."""
        src = tmp_path / "src" / "Draft.pdf"
        src.parent.mkdir()
        dest = tmp_path / "out"
        dest.mkdir()
        _, _, md, img, cover = _intermediate_paths(src, dest)
        assert md.parent == dest
        assert img.parent == dest
        assert cover.parent == dest

    def test_names_are_unchanged_by_rerooting(self, tmp_path):
        dest = tmp_path / "out"
        src = tmp_path / "Draft.pdf"
        base = _intermediate_paths(src)
        moved = _intermediate_paths(src, dest)
        assert [p.name for p in base[2:]] == [p.name for p in moved[2:]]


class TestStemClaiming:
    def test_same_stem_from_different_folders_stays_distinct(self, tmp_path):
        """Two `Book.pdf` sharing one destination must not overwrite each other."""
        dest = tmp_path / "out"
        a = tmp_path / "fiction" / "Book.pdf"
        b = tmp_path / "history" / "Book.pdf"
        claimed: set[str] = set()
        _, _, md_a, img_a, cov_a = _intermediate_paths(a, dest, claimed)
        _, _, md_b, img_b, cov_b = _intermediate_paths(b, dest, claimed)
        assert md_a != md_b and img_a != img_b and cov_a != cov_b

    def test_the_bumped_set_stays_coherent(self, tmp_path):
        """C2: one resolved stem for all three, or the markdown points at an
        image folder that does not exist."""
        dest = tmp_path / "out"
        claimed: set[str] = set()
        _intermediate_paths(tmp_path / "a" / "Book.pdf", dest, claimed)
        _, _, md, img, cover = _intermediate_paths(tmp_path / "b" / "Book.pdf",
                                                   dest, claimed)
        stem = md.stem                                  # e.g. "Book_pdf (1)"
        assert img.name == f"{stem}_img"
        assert cover.name == f"{stem}_cover.png"

    def test_three_way_collision_keeps_climbing(self, tmp_path):
        dest = tmp_path / "out"
        claimed: set[str] = set()
        stems = [
            _intermediate_paths(tmp_path / d / "Book.pdf", dest, claimed)[2].stem
            for d in ("a", "b", "c")
        ]
        assert stems == ["Book_pdf", "Book_pdf (1)", "Book_pdf (2)"]

    def test_reruns_do_not_accumulate(self, tmp_path):
        """C3: a fresh run starts a fresh claim set, so converting the same file
        twice overwrites its own artifacts instead of piling up (1), (2), ..."""
        dest = tmp_path / "out"
        first = _intermediate_paths(tmp_path / "Book.pdf", dest, set())[2]
        second = _intermediate_paths(tmp_path / "Book.pdf", dest, set())[2]
        assert first == second

    def test_no_claim_set_never_bumps(self, tmp_path):
        """Single-file conversions pass no claim set and must behave as before."""
        src = tmp_path / "Book.pdf"
        assert _intermediate_paths(src)[2] == _intermediate_paths(src)[2]

    def test_different_source_formats_still_disambiguate(self, tmp_path):
        """The v0.2.0 guard still holds and does not consume a bump."""
        dest = tmp_path / "out"
        claimed: set[str] = set()
        a = _intermediate_paths(tmp_path / "Draft.pdf", dest, claimed)[2]
        b = _intermediate_paths(tmp_path / "Draft.docx", dest, claimed)[2]
        assert a.name == "Draft_pdf.md" and b.name == "Draft_docx.md"


def _md_source(tmp_path: Path) -> Path:
    """A markdown source with a real image reference, ready to convert."""
    img_dir = tmp_path / "src" / "Note_md_img"
    img_dir.mkdir(parents=True)
    write_png(img_dir / "shot.png", 40, 40)
    src = tmp_path / "src" / "Note.md"
    src.write_text("# Note\n\n![](Note_md_img/shot.png)\n", encoding="utf-8")
    return src


class TestConversionHonoursTheRoot:
    def test_every_artifact_lands_in_the_destination(self, tmp_path, log_q):
        src = _md_source(tmp_path)
        dest = tmp_path / "out"
        dest.mkdir()
        out = _run_single(
            pipeline.ConvertParams(src=src, target_fmt="pdf", mode="standard",
                                   extract_cover=False, dest_dir=dest),
            log_q,
        )
        assert out.parent == dest
        assert (dest / "Note_md.md").exists()
        assert not (src.parent / "Note_md.md").exists(), "nothing beside the source"

    def test_images_still_resolve_after_rerooting(self, tmp_path, log_q):
        """The case unit tests miss: the reference must still find the image."""
        src = _md_source(tmp_path)
        dest = tmp_path / "out"
        dest.mkdir()
        out = _run_single(
            pipeline.ConvertParams(src=src, target_fmt="pdf", mode="standard",
                                   extract_cover=False, dest_dir=dest),
            log_q,
        )
        with pymupdf.open(str(out)) as doc:
            assert len(doc[0].get_images(full=True)) == 1, (
                "image lost - the md/img sibling contract broke when rerooted"
            )


class TestCleanup:
    """Uses a DOCX source, because that actually generates a hub .md and an
    image folder - a passthrough .md produces no `_img/` at all."""

    def _convert(self, sample_docx, tmp_path, log_q, *, keep: bool,
                 extract_cover=False):
        dest = tmp_path / "out"
        dest.mkdir(exist_ok=True)
        out = _run_single(
            pipeline.ConvertParams(src=sample_docx, target_fmt="pdf",
                                   mode="standard", extract_cover=extract_cover,
                                   dest_dir=dest, keep_intermediates=keep),
            log_q,
        )
        return out, dest

    def test_kept_by_default(self, sample_docx, tmp_path, log_q):
        _, dest = self._convert(sample_docx, tmp_path, log_q, keep=True)
        assert (dest / "Sample Doc_docx.md").exists()
        assert (dest / "Sample Doc_docx_img").is_dir()

    def test_removed_when_disabled(self, sample_docx, tmp_path, log_q):
        out, dest = self._convert(sample_docx, tmp_path, log_q, keep=False)
        assert out.exists(), "the deliverable survives"
        assert not (dest / "Sample Doc_docx.md").exists()
        assert not (dest / "Sample Doc_docx_img").exists()

    def test_cover_is_never_removed(self, sample_docx, tmp_path, log_q):
        """The queue panel previews it; deleting it blanks the preview."""
        _, dest = self._convert(sample_docx, tmp_path, log_q, keep=False,
                                extract_cover=True)
        covers = list(dest.glob("*_cover.png"))
        assert covers, "cover must outlive the cleanup"

    def test_passthrough_hub_is_removed_but_the_source_is_not(self, tmp_path, log_q):
        """For fmt == md the hub is scaffolding; the source is not ours to delete."""
        src = _md_source(tmp_path)
        dest = tmp_path / "out"
        dest.mkdir()
        out = _run_single(
            pipeline.ConvertParams(src=src, target_fmt="md", mode="standard",
                                   extract_cover=False, dest_dir=dest,
                                   keep_intermediates=False),
            log_q,
        )
        assert out.exists() and out.parent == dest
        assert not (dest / "Note_md.md").exists(), "hub is an intermediate"
        assert src.exists(), "the user's source file must never be deleted"

    def test_failure_preserves_the_evidence(self, sample_docx, tmp_path, log_q,
                                            monkeypatch):
        """On failure the intermediates are the diagnostics - keep them."""
        dest = tmp_path / "out"
        dest.mkdir()

        def boom(*a, **k):
            raise RuntimeError("generator exploded")

        monkeypatch.setattr(pipeline.from_markdown, "convert", boom)
        with pytest.raises(RuntimeError):
            _run_single(
                pipeline.ConvertParams(src=sample_docx, target_fmt="pdf",
                                       mode="standard", extract_cover=False,
                                       dest_dir=dest, keep_intermediates=False),
                log_q,
            )
        assert (dest / "Sample Doc_docx.md").exists(), "hub must survive a failure"
        assert (dest / "Sample Doc_docx_img").is_dir()

    def test_cleanup_failure_does_not_fail_the_conversion(self, sample_docx,
                                                          tmp_path, log_q,
                                                          monkeypatch):
        """Being unable to delete a scratch file is a warning, not an error."""
        def denied(*a, **k):
            raise OSError("in use by another process")

        monkeypatch.setattr(shutil, "rmtree", denied)
        monkeypatch.setattr(Path, "unlink", denied)

        out, _ = self._convert(sample_docx, tmp_path, log_q, keep=False)
        assert out.exists(), "conversion still succeeded"
        assert any("Could not remove" in m for m in drain(log_q))


class TestDestinationValidation:
    def test_missing_destination_aborts_the_batch_cleanly(self, tmp_path, log_q):
        """Falling back per-file would scatter output across two folders."""
        src = _md_source(tmp_path)
        gone = tmp_path / "not_here"
        pipeline.run_batch([src], "pdf", "standard", False, log_q,
                           dest_dir=gone)
        msgs = drain(log_q)
        assert any("Output folder is unavailable" in m for m in msgs)
        assert not any(m.startswith("__FILE_START__") for m in msgs), (
            "no file should have been attempted"
        )

    def test_existing_destination_runs(self, tmp_path, log_q):
        src = _md_source(tmp_path)
        dest = tmp_path / "out"
        dest.mkdir()
        pipeline.run_batch([src], "pdf", "standard", False, log_q, dest_dir=dest)
        assert (dest / "Note.pdf").exists()

"""Guards for the pandoc output path.

Regression cover for the --resource-path double-nesting bug: image references in
the hub markdown already contain the img-folder name, so pointing
--resource-path at the img folder made pandoc look for img_dir/img_dir/x.png and
silently drop every image from EPUB and DOCX output.
"""

import os
import zipfile
from pathlib import Path

import pytest

from conftest import write_png
from omniconvert.converters import from_markdown

# The app prepends the vendored pandoc to PATH at import time; do the same here.
_VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "pandoc"
if _VENDOR.is_dir() and str(_VENDOR) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(_VENDOR) + os.pathsep + os.environ.get("PATH", "")


def _pandoc_available() -> bool:
    try:
        import pypandoc

        pypandoc.get_pandoc_version()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pandoc_available(),
    reason="pandoc not installed - run scripts/install_pandoc.py",
)


@pytest.fixture
def md_with_image(tmp_path):
    """A hub .md plus its img folder, named the way the pipeline names them.

    The stem carries a space so the percent-encoded reference is exercised.
    """
    img_dir = tmp_path / "Sample Doc_docx_img"
    img_dir.mkdir()
    write_png(img_dir / "img_001.png", width=40, height=40)
    md = tmp_path / "Sample Doc_docx.md"
    md.write_text(
        "# Heading\n\nBody text.\n\n![](Sample%20Doc_docx_img/img_001.png)\n",
        encoding="utf-8",
    )
    return md, img_dir


def _members(archive: Path, suffixes=(".png", ".jpg", ".jpeg")):
    with zipfile.ZipFile(archive) as zf:
        return [n for n in zf.namelist() if n.lower().endswith(suffixes)]


def test_epub_embeds_the_referenced_image(md_with_image, tmp_path, log_q):
    md, img_dir = md_with_image
    out = tmp_path / "out.epub"
    from_markdown.convert(md, img_dir, None, "epub", out, log_q)
    assert _members(out), "EPUB contains no image - resource-path regression"


def test_docx_embeds_the_referenced_image(md_with_image, tmp_path, log_q):
    md, img_dir = md_with_image
    out = tmp_path / "out.docx"
    from_markdown.convert(md, img_dir, None, "docx", out, log_q)
    assert _members(out), "DOCX contains no image - resource-path regression"


def test_pandoc_reports_no_missing_resources(md_with_image, tmp_path, log_q, capfd):
    md, img_dir = md_with_image
    from_markdown.convert(md, img_dir, None, "epub", tmp_path / "out.epub", log_q)
    combined = "".join(capfd.readouterr())
    assert "Could not fetch resource" not in combined


def test_txt_output_is_produced(md_with_image, tmp_path, log_q):
    md, img_dir = md_with_image
    out = tmp_path / "out.txt"
    from_markdown.convert(md, img_dir, None, "txt", out, log_q)
    assert "Heading" in out.read_text(encoding="utf-8")

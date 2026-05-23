import io
import itertools
import mimetypes
import shutil
import urllib.parse
import warnings
from pathlib import Path
from queue import Queue

warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")

# markitdown runs this pre-pass over the DOCX stream before handing it to mammoth;
# it converts OMML (Word equation) markup to LaTeX. We drive mammoth directly so we
# can control image extraction, which means applying the pre-pass ourselves. It
# lives in a private markitdown module, so degrade gracefully if that moves.
try:
    from markitdown.converter_utils.docx.pre_process import (
        pre_process_docx as _pre_process_docx,
    )
except ImportError:  # pragma: no cover - depends on markitdown internals
    def _pre_process_docx(stream):
        return stream


def convert(src: Path, md_out: Path, img_dir: Path, log_q: Queue) -> None:
    """Convert src to Markdown, writing images to img_dir and text to md_out."""
    suffix = src.suffix.lower()

    if suffix == ".pdf":
        _from_pdf(src, md_out, img_dir, log_q)
    elif suffix == ".docx":
        _from_docx(src, md_out, img_dir, log_q)
    elif suffix == ".epub":
        _from_epub(src, md_out, img_dir, log_q)
    elif suffix == ".txt":
        _from_txt(src, md_out, log_q)
    elif suffix == ".md":
        shutil.copy2(str(src), str(md_out))
        log_q.put(f"[✓] Markdown: {md_out.name} (passthrough)")
    else:
        raise ValueError(f"Unsupported input format: {suffix}")


def _from_pdf(src: Path, md_out: Path, img_dir: Path, log_q: Queue) -> None:
    import pymupdf4llm

    log_q.put("[*] Parsing PDF → Markdown (with images)...")
    img_dir.mkdir(parents=True, exist_ok=True)

    md_text = pymupdf4llm.to_markdown(
        str(src),
        write_images=True,
        image_path=str(img_dir),
        image_format="png",
    )
    md_out.write_text(md_text, encoding="utf-8")

    img_count = len(list(img_dir.glob("*")))
    log_q.put(f"[✓] Markdown saved: {md_out.name}  |  {img_count} image(s) → {img_dir.name}/")


def _from_docx(src: Path, md_out: Path, img_dir: Path, log_q: Queue) -> None:
    """DOCX → Markdown with embedded images written to img_dir as real files.

    mammoth's default image handler (`images.data_uri`) inlines every image as a
    base64 data URI. That bloats the hub .md by ~33% and leaves img_dir empty,
    which in turn makes pandoc's --resource-path / --extract-media flags no-ops
    downstream. We supply our own handler so DOCX behaves like the PDF and EPUB
    paths: real image files on disk, relative references in the markdown.

    The HTML mammoth produces is still run through markitdown's converter so we
    keep its table and heading fidelity.
    """
    import mammoth
    from markitdown import MarkItDown, StreamInfo

    log_q.put("[*] Parsing DOCX → Markdown (with images)...")
    img_dir.mkdir(parents=True, exist_ok=True)
    counter = itertools.count(1)

    @mammoth.images.img_element
    def _save_image(image):
        with image.open() as fh:
            data = fh.read()
        ext = mimetypes.guess_extension(image.content_type or "") or ".png"
        if ext == ".jpe":  # some installs map image/jpeg to .jpe
            ext = ".jpg"
        name = f"img_{next(counter):03d}{ext}"
        (img_dir / name).write_bytes(data)
        # The reference MUST include the img-folder name: weasyprint resolves it
        # against the .md file's parent (see from_markdown._to_pdf). Percent-encode
        # the folder segment so stems containing spaces still parse as one URL.
        return {"src": f"{urllib.parse.quote(img_dir.name)}/{name}"}

    with src.open("rb") as fh:
        html = mammoth.convert_to_html(
            _pre_process_docx(fh), convert_image=_save_image
        ).value

    md_text = MarkItDown().convert_stream(
        io.BytesIO(html.encode("utf-8")),
        stream_info=StreamInfo(
            mimetype="text/html", extension=".html", charset="utf-8"
        ),
    ).text_content

    md_out.write_text(md_text, encoding="utf-8")

    img_count = len(list(img_dir.glob("*")))
    log_q.put(f"[✓] Markdown saved: {md_out.name}  |  {img_count} image(s) → {img_dir.name}/")


def _from_epub(src: Path, md_out: Path, img_dir: Path, log_q: Queue) -> None:
    import ebooklib
    from ebooklib import epub
    import html2text

    log_q.put("[*] Parsing EPUB → Markdown...")
    img_dir.mkdir(parents=True, exist_ok=True)
    book = epub.read_epub(str(src), options={"ignore_ncx": True})

    h2t = html2text.HTML2Text()
    h2t.ignore_links = False
    h2t.ignore_images = False
    h2t.body_width = 0  # no hard line wrapping

    chapters = []
    img_count = 0

    # Extract and save embedded images
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            img_path = img_dir / Path(item.file_name).name
            img_path.write_bytes(item.get_content())
            img_count += 1

    # Convert spine chapters in order
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html_content = item.get_content().decode("utf-8", errors="replace")
        md_chunk = h2t.handle(html_content)
        if md_chunk.strip():
            chapters.append(md_chunk)

    full_md = "\n\n---\n\n".join(chapters)
    md_out.write_text(full_md, encoding="utf-8")
    log_q.put(f"[✓] Markdown saved: {md_out.name}  |  {img_count} image(s) → {img_dir.name}/")


def _from_txt(src: Path, md_out: Path, log_q: Queue) -> None:
    log_q.put("[*] Reading TXT → Markdown...")
    text = src.read_text(encoding="utf-8", errors="replace")
    md_out.write_text(text, encoding="utf-8")
    log_q.put(f"[✓] Markdown saved: {md_out.name}")

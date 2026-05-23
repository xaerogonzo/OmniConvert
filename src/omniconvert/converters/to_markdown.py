import io
import shutil
import warnings
from pathlib import Path
from queue import Queue

warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")


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
    from markitdown import MarkItDown

    log_q.put("[*] Parsing DOCX → Markdown...")
    md_obj = MarkItDown()
    result = md_obj.convert(str(src))
    md_text = result.text_content

    # markitdown may embed images as base64 or relative paths; save as-is
    md_out.write_text(md_text, encoding="utf-8")
    log_q.put(f"[✓] Markdown saved: {md_out.name}")


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

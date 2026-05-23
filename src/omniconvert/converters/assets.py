import zipfile
import warnings
from pathlib import Path
from queue import Queue

warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")


def extract_cover(src: Path, log_q: Queue, out: Path | None = None) -> Path | None:
    """Extract the primary cover/first-page image from src and save as PNG.

    If `out` is provided, write there; otherwise default to `{src.stem}_cover.png`
    next to the source. Returns the cover path on success, None on failure.
    """
    suffix = src.suffix.lower()
    if out is None:
        out = src.with_name(src.stem + "_cover.png")

    try:
        if suffix == ".pdf":
            return _cover_pdf(src, out, log_q)
        elif suffix == ".docx":
            return _cover_docx(src, out, log_q)
        elif suffix == ".epub":
            return _cover_epub(src, out, log_q)
    except Exception as exc:
        log_q.put(f"[!] Cover extraction failed: {exc}")

    return None


def _cover_pdf(src: Path, out: Path, log_q: Queue) -> Path | None:
    import pymupdf
    from PIL import Image
    import io

    doc = pymupdf.open(str(src))
    page = doc[0]

    # Check for large embedded images on page 0
    best_img_data = None
    best_area = 0
    for xref in page.get_images(full=True):
        base_xref = xref[0]
        try:
            img_dict = doc.extract_image(base_xref)
            w, h = img_dict["width"], img_dict["height"]
            area = w * h
            if area > best_area and area > 10000:
                best_area = area
                best_img_data = img_dict["image"]
                best_w, best_h = w, h
        except Exception:
            continue

    # Render page at 2× if no large embedded image, or if embedded image is smaller
    mat = pymupdf.Matrix(2, 2)
    pix = page.get_pixmap(matrix=mat)
    page_area = pix.width * pix.height

    if best_img_data and best_area > page_area * 0.25:
        img = Image.open(io.BytesIO(best_img_data))
        img.save(str(out), "PNG")
        log_q.put(f"[✓] Cover: {best_w}×{best_h} px (embedded) → {out.name}")
    else:
        pix.save(str(out))
        log_q.put(f"[✓] Cover: {pix.width}×{pix.height} px (page render) → {out.name}")

    doc.close()
    return out


def _cover_docx(src: Path, out: Path, log_q: Queue) -> Path | None:
    from PIL import Image
    import io

    min_size = 5 * 1024  # 5 KB — skip icon-sized junk

    with zipfile.ZipFile(str(src), "r") as zf:
        media = [
            info for info in zf.infolist()
            if info.filename.startswith("word/media/") and info.file_size > min_size
        ]
        if not media:
            log_q.put("[!] No media files found in DOCX")
            return None

        largest = max(media, key=lambda i: i.file_size)
        data = zf.read(largest.filename)

    img = Image.open(io.BytesIO(data))
    img.save(str(out), "PNG")
    log_q.put(f"[✓] Cover: {img.width}×{img.height} px → {out.name}")
    return out


def _cover_epub(src: Path, out: Path, log_q: Queue) -> Path | None:
    import ebooklib
    from ebooklib import epub
    from PIL import Image
    import io

    book = epub.read_epub(str(src), options={"ignore_ncx": True})

    # Try explicit cover-image id first
    cover_item = book.get_item_with_id("cover-image")

    # Scan items for ITEM_COVER type
    if cover_item is None:
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_COVER:
                cover_item = item
                break

    # Fallback: first image in the manifest
    if cover_item is None:
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_IMAGE:
                cover_item = item
                break

    if cover_item is None:
        log_q.put("[!] No cover image found in EPUB")
        return None

    img = Image.open(io.BytesIO(cover_item.get_content()))
    img.save(str(out), "PNG")
    log_q.put(f"[✓] Cover: {img.width}×{img.height} px → {out.name}")
    return out

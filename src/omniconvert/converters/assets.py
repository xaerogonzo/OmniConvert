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


#: A cover is page-sized. Anything below this on its shorter edge is a logo,
#: bullet or signature - regardless of how many bytes it occupies.
_MIN_COVER_EDGE = 200

#: Decoding every image in a long document is wasteful, so only the largest few
#: by stored size are inspected. A cover is never among the smallest.
_MAX_COVER_CANDIDATES = 12


def _cover_docx(src: Path, out: Path, log_q: Queue) -> Path | None:
    """Pick the DOCX's cover by image DIMENSIONS, not by byte size.

    The old rule took the largest file over 5 KB. Byte size is a poor proxy for
    "is this a cover": a heavily-compressed full-page photo can sit under 5 KB
    and be skipped entirely, while a noisy 64x64 icon sails past the floor.
    """
    from PIL import Image
    import io

    with zipfile.ZipFile(str(src), "r") as zf:
        media = sorted(
            (i for i in zf.infolist() if i.filename.startswith("word/media/")),
            key=lambda i: i.file_size,
            reverse=True,
        )
        if not media:
            log_q.put("[!] No media files found in DOCX")
            return None
        candidates = [(i.filename, zf.read(i.filename))
                      for i in media[:_MAX_COVER_CANDIDATES]]

    page_sized: tuple[int, Image.Image] | None = None
    any_image: tuple[int, Image.Image] | None = None

    for name, data in candidates:
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception:
            continue          # EMF/WMF vector art, or simply corrupt
        area = img.width * img.height
        if any_image is None or area > any_image[0]:
            any_image = (area, img)
        if min(img.size) >= _MIN_COVER_EDGE and (
            page_sized is None or area > page_sized[0]
        ):
            page_sized = (area, img)

    # Fall back to the biggest decodable image rather than giving up: a small
    # cover is still better than none, and the old rule would have taken it.
    chosen = page_sized or any_image
    if chosen is None:
        log_q.put("[!] No decodable image found in DOCX")
        return None

    img = chosen[1]
    if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        img = img.convert("RGB")   # CMYK JPEGs cannot be written as PNG
    img.save(str(out), "PNG")

    note = "" if page_sized else "  (small - may not be a real cover)"
    log_q.put(f"[✓] Cover: {img.width}×{img.height} px → {out.name}{note}")
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

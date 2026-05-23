import shutil
import warnings
from pathlib import Path
from queue import Queue

warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")

# Page geometry for the MD → PDF path. PyMuPDF's Story renderer ignores
# `max-width` and `margin: auto`, so the text column is established by the
# placement rectangle instead of by CSS (see _to_pdf).
_PAGE_MARGIN_PT = 54.0          # 0.75 inch
_CONTENT_WIDTH_PT = 525.0       # ≈ the old 700px column at 96 dpi
_MAX_PAGES = 5000               # runaway guard: Story.place() never converging

# Shared typography for the MD → PDF path. Every rule here was verified to take
# effect in PyMuPDF Story; `page-break-after` is omitted because it does not.
_BASE_CSS = """
    body { font-family: Georgia, serif; font-size: 11pt; line-height: 1.6;
           color: #1a1a1a; }
    h1, h2, h3, h4 { font-family: 'Helvetica Neue', Arial, sans-serif; }
    code { background: #f5f5f5; padding: 2px 4px; font-family: monospace; }
    pre code { display: block; padding: 12px; }
    img { max-width: 100%; height: auto; }
"""

# "Strict Table Grid" ON — every cell ruled, header band shaded.
_TABLE_CSS_STRICT = """
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ccc; padding: 6px 10px; }
    th { background: #f0f0f0; }
"""

# "Strict Table Grid" OFF — borderless, relies on whitespace and a bold header.
_TABLE_CSS_PLAIN = """
    table { border-collapse: collapse; width: 100%; }
    th, td { border: none; padding: 6px 10px; }
    th { background: transparent; font-weight: bold; text-align: left; }
"""


def convert(
    md_path: Path,
    img_dir: Path,
    cover_path: Path | None,
    target_fmt: str,
    out_path: Path,
    log_q: Queue,
    strict_tables: bool = True,
) -> None:
    """Convert md_path to target_fmt and write to out_path.
    img_dir is the folder containing extracted images referenced by the markdown.
    strict_tables draws ruled table borders on the PDF path."""
    fmt = target_fmt.lower()

    if fmt == "pdf":
        _to_pdf(md_path, out_path, log_q, strict_tables=strict_tables)
    elif fmt == "docx":
        _to_pandoc(md_path, img_dir, "docx", out_path, log_q)
    elif fmt == "epub":
        _to_pandoc(md_path, img_dir, "epub3", out_path, log_q, cover_path=cover_path)
    elif fmt == "txt":
        _to_pandoc(md_path, img_dir, "plain", out_path, log_q)
    elif fmt == "md":
        shutil.copy2(str(md_path), str(out_path))
        log_q.put(f"[✓] Done: {out_path.name}")
    else:
        raise ValueError(f"Unsupported output format: {fmt}")


def _to_pdf(
    md_path: Path, out_path: Path, log_q: Queue, strict_tables: bool = True
) -> None:
    """MD → PDF via PyMuPDF's Story renderer: markdown lib → HTML → PDF.

    Needs no pandoc, no LaTeX, and — unlike weasyprint — no system libraries.
    weasyprint requires the GTK/Pango DLLs on Windows, which cannot be bundled
    into the Nuitka one-file build, so it could never produce a PDF from the
    portable .exe on a machine that lacked them.

    NOTE on the archive root: image references inside the markdown ALREADY
    include the img-folder name (e.g. `![](Draft_pdf_img/x.png)`). The archive
    must therefore be the directory CONTAINING the .md, NOT the image folder —
    the same contract the pandoc path's --resource-path relies on. Pointing it
    at the image folder makes every reference resolve one level too deep.
    """
    import markdown
    import pymupdf

    log_q.put("[*] Converting MD → PDF via PyMuPDF...")

    md_text = md_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "nl2br"],
    )

    css = _BASE_CSS + (_TABLE_CSS_STRICT if strict_tables else _TABLE_CSS_PLAIN)
    full_html = f"<html><head><style>{css}</style></head><body>{html_body}</body></html>"

    story = pymupdf.Story(html=full_html, archive=str(md_path.parent))
    writer = pymupdf.DocumentWriter(str(out_path))

    page_rect = pymupdf.paper_rect("letter")
    width = min(_CONTENT_WIDTH_PT, page_rect.width - 2 * _PAGE_MARGIN_PT)
    x0 = (page_rect.width - width) / 2
    frame = pymupdf.Rect(
        x0, _PAGE_MARGIN_PT, x0 + width, page_rect.height - _PAGE_MARGIN_PT
    )

    try:
        more = 1
        pages = 0
        while more:
            if pages >= _MAX_PAGES:
                raise RuntimeError(
                    f"PDF layout did not converge after {_MAX_PAGES} pages "
                    f"(content too wide for the page?)"
                )
            device = writer.begin_page(page_rect)
            more, _ = story.place(frame)
            story.draw(device)
            writer.end_page()
            pages += 1
    finally:
        writer.close()

    log_q.put(f"[✓] Done: {out_path.name}  ({pages} page(s))")


def _to_pandoc(
    md_path: Path,
    img_dir: Path,
    pandoc_fmt: str,
    out_path: Path,
    log_q: Queue,
    cover_path: Path | None = None,
) -> None:
    import pypandoc

    fmt_label = pandoc_fmt.upper().replace("3", "")
    log_q.put(f"[*] Converting MD → {fmt_label} via pandoc...")

    # Image references inside the markdown already include the img-folder name
    # (e.g. `![](Draft_pdf_img/x.png)`), exactly like the weasyprint path. So the
    # resource path must be the directory CONTAINING the .md, NOT the img folder
    # itself — pointing it at img_dir makes pandoc look for img_dir/img_dir/x.png
    # and silently drop every image.
    extra_args: list[str] = [f"--resource-path={md_path.parent}"]

    if pandoc_fmt == "epub3" and cover_path and cover_path.exists():
        extra_args += [f"--epub-cover-image={cover_path}"]

    pypandoc.convert_file(
        str(md_path),
        pandoc_fmt,
        outputfile=str(out_path),
        extra_args=extra_args,
    )
    log_q.put(f"[✓] Done: {out_path.name}")

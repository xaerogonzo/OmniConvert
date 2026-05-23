import shutil
import warnings
from pathlib import Path
from queue import Queue

warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")


def convert(
    md_path: Path,
    img_dir: Path,
    cover_path: Path | None,
    target_fmt: str,
    out_path: Path,
    log_q: Queue,
) -> None:
    """Convert md_path to target_fmt and write to out_path.
    img_dir is the folder containing extracted images referenced by the markdown."""
    fmt = target_fmt.lower()

    if fmt == "pdf":
        _to_pdf(md_path, out_path, log_q)
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


def _to_pdf(md_path: Path, out_path: Path, log_q: Queue) -> None:
    """Primary MD → PDF path: markdown lib → HTML → weasyprint.
    No pandoc or LaTeX required.

    NOTE on base_url: pymupdf4llm and other parsers write image references
    that ALREADY include the img-folder name (e.g. `![](Draft_pdf_img/x.png)`).
    base_url must therefore be the directory CONTAINING the .md file, NOT the
    image folder itself — otherwise weasyprint double-nests and breaks images.
    """
    import markdown
    from weasyprint import HTML

    log_q.put("[*] Converting MD → PDF via weasyprint...")

    md_text = md_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "nl2br"],
    )

    css = """
    body { font-family: Georgia, serif; font-size: 11pt; line-height: 1.6;
           max-width: 700px; margin: 40px auto; color: #1a1a1a; }
    h1, h2, h3, h4 { font-family: 'Helvetica Neue', Arial, sans-serif;
                      page-break-after: avoid; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ccc; padding: 6px 10px; }
    th { background: #f0f0f0; }
    code { background: #f5f5f5; padding: 2px 4px; font-family: monospace; }
    pre code { display: block; padding: 12px; overflow-x: auto; }
    img { max-width: 100%; height: auto; }
    """

    full_html = f"<html><head><style>{css}</style></head><body>{html_body}</body></html>"

    # base_url is the .md file's parent — relative img paths in the .md already
    # contain the img-folder name, so this resolves correctly without nesting.
    HTML(string=full_html, base_url=md_path.parent.as_uri()).write_pdf(str(out_path))
    log_q.put(f"[✓] Done: {out_path.name}")


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

    extra_args: list[str] = []

    if img_dir.exists():
        extra_args += [f"--resource-path={img_dir}"]

    if pandoc_fmt == "epub3" and cover_path and cover_path.exists():
        extra_args += [f"--epub-cover-image={cover_path}"]

    if pandoc_fmt == "docx" and img_dir.exists():
        extra_args += [f"--extract-media={img_dir}"]

    pypandoc.convert_file(
        str(md_path),
        pandoc_fmt,
        outputfile=str(out_path),
        extra_args=extra_args,
    )
    log_q.put(f"[✓] Done: {out_path.name}")

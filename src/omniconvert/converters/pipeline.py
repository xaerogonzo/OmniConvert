"""Conversion pipeline orchestrator.

All conversion work runs on a background daemon thread spawned by `start()` or
`start_batch()`. The pipeline posts progress strings to a queue.Queue that the
GUI polls; it never touches Tk widgets directly.

Markers the GUI watches for:
    __DONE__<path>          single-file run completed (legacy single-file path)
    __ERROR__               single-file run failed
    __FILE_START__<idx>     batch: file idx starting
    __FILE_DONE__<idx>      batch: file idx succeeded
    __FILE_ERROR__<idx>     batch: file idx failed (batch continues)
    __BATCH_DONE__          batch run completed (success+failure totals already logged)
"""

import gc
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Literal

from . import assets, from_markdown, hifi, to_markdown

Mode = Literal["standard", "hifi"]


@dataclass
class ConvertParams:
    src: Path
    target_fmt: str          # "pdf" | "docx" | "epub" | "md" | "txt"
    mode: Mode
    extract_cover: bool


def sanitize_stem(name: str) -> str:
    """Make a filename stem safe for Windows.
    Replaces ':' with '-', collapses whitespace, strips trailing dots, and
    prefixes Windows-reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)."""
    name = name.replace(":", "-")
    name = re.sub(r"\s+", " ", name).strip()
    name = name.strip(". ")
    if re.match(r"^(CON|PRN|AUX|NUL|COM\d|LPT\d)$", name, re.IGNORECASE):
        name = "_" + name
    return name


def _unique_path(p: Path) -> Path:
    """Return p if it doesn't exist, else p with a (1), (2)... suffix on the stem."""
    if not p.exists():
        return p
    i = 1
    while True:
        cand = p.with_stem(f"{p.stem} ({i})")
        if not cand.exists():
            return cand
        i += 1


def _intermediate_paths(src: Path) -> tuple[str, str, Path, Path, Path]:
    """Compute collision-safe paths for the intermediate artifacts.

    Stems are suffixed with the source extension so that `Draft.pdf` and
    `Draft.docx` in the same folder don't overwrite each other's intermediates.

    Returns (stem, src_ext, md_path, img_dir, cover_path).
    """
    src_ext = src.suffix.lower().lstrip(".")
    stem = sanitize_stem(src.stem)
    base_stem = f"{stem}_{src_ext}"
    parent = src.parent
    md_path = parent / f"{base_stem}.md"
    img_dir = parent / f"{base_stem}_img"
    cover_path = parent / f"{base_stem}_cover.png"
    return stem, src_ext, md_path, img_dir, cover_path


def _run_single(params: ConvertParams, log_q: Queue) -> Path:
    """Run one conversion. Returns the final output path on success, raises on error.

    Does NOT post __DONE__ / __ERROR__ markers — those are added by the public
    wrappers (`run`, `run_batch`) so batch mode can attach per-file markers.

    Always forces gc.collect() at the end to free PyMuPDF's C-allocated memory.
    """
    src = params.src
    fmt = params.target_fmt.lower()
    stem, src_ext, md_path, img_dir, cover_path_intermediate = _intermediate_paths(src)
    parent = src.parent

    # Final output uses the user-friendly bare stem (no _ext suffix); guarded
    # against same-format collisions via _unique_path.
    out_path = _unique_path(parent / f"{stem}.{fmt}")

    log_q.put(
        f"[*] Mode: {'High-Fidelity' if params.mode == 'hifi' else 'Standard'} | "
        f"{src.suffix.upper().lstrip('.')} → {fmt.upper()}"
    )

    try:
        # ---- High-Fidelity paths (bypass the Markdown hub) ----------------
        if params.mode == "hifi" and src.suffix.lower() == ".pdf" and fmt == "docx":
            hifi.pdf_to_docx(src, out_path, log_q)
            if params.extract_cover:
                assets.extract_cover(src, log_q, out=cover_path_intermediate)
            log_q.put("[✓] Conversion complete.")
            return out_path

        if params.mode == "hifi" and src.suffix.lower() == ".docx" and fmt == "pdf":
            try:
                hifi.docx_to_pdf(src, out_path, log_q)
                if params.extract_cover:
                    assets.extract_cover(src, log_q, out=cover_path_intermediate)
                log_q.put("[✓] Conversion complete.")
                return out_path
            except (ImportError, Exception) as exc:
                # MS Word missing or COM failed — degrade to Standard
                log_q.put(f"[!] MS Word path unavailable ({type(exc).__name__}) "
                          f"— falling back to weasyprint (lower fidelity)")
                # fall through to Standard path below

        # ---- Standard hub-and-spoke path ---------------------------------
        if src.suffix.lower() != ".md":
            to_markdown.convert(src, md_path, img_dir, log_q)
        else:
            if src != md_path:
                shutil.copy2(str(src), str(md_path))
            log_q.put(f"[✓] Markdown: {md_path.name} (passthrough)")

        cover_path: Path | None = None
        if params.extract_cover and src.suffix.lower() in {".pdf", ".docx", ".epub"}:
            cover_path = assets.extract_cover(src, log_q, out=cover_path_intermediate)

        if fmt == "md":
            # Output IS the markdown hub — copy to the bare-stem .md if needed
            if md_path != out_path:
                shutil.copy2(str(md_path), str(out_path))
            log_q.put(f"[✓] Done: {out_path.name}")
            return out_path

        from_markdown.convert(md_path, img_dir, cover_path, fmt, out_path, log_q)
        log_q.put("[✓] Conversion complete.")
        return out_path
    finally:
        # Free PyMuPDF C-allocated buffers between files — critical for batch runs
        gc.collect()


# ---------------------------------------------------------------------------
# Single-file public API (kept for backward compatibility)
# ---------------------------------------------------------------------------

def run(params: ConvertParams, log_q: Queue) -> None:
    """Single-file conversion. Posts __DONE__/__ERROR__ markers."""
    try:
        out_path = _run_single(params, log_q)
        log_q.put(f"__DONE__{out_path}")
    except Exception as exc:
        log_q.put(f"[✗] Error: {exc}")
        log_q.put("__ERROR__")


def start(params: ConvertParams, log_q: Queue) -> threading.Thread:
    """Spawn a daemon thread and start a single-file pipeline."""
    t = threading.Thread(target=run, args=(params, log_q), daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Batch public API
# ---------------------------------------------------------------------------

def run_batch(
    sources: list[Path],
    target_fmt: str,
    mode: Mode,
    extract_cover: bool,
    log_q: Queue,
) -> None:
    """Process a list of source files sequentially.

    Continues on individual failures. Posts per-file markers
    (__FILE_START__N / __FILE_DONE__N / __FILE_ERROR__N) and a final
    __BATCH_DONE__ marker when complete.
    """
    succeeded = failed = 0
    total = len(sources)

    for i, src in enumerate(sources):
        log_q.put(f"__FILE_START__{i}")
        log_q.put(f"[*] === ({i + 1}/{total}) {src.name} ===")
        params = ConvertParams(
            src=src,
            target_fmt=target_fmt,
            mode=mode,
            extract_cover=extract_cover,
        )
        try:
            _run_single(params, log_q)
            log_q.put(f"__FILE_DONE__{i}")
            succeeded += 1
        except Exception as exc:
            log_q.put(f"[✗] {src.name}: {exc}")
            log_q.put(f"__FILE_ERROR__{i}")
            failed += 1

    log_q.put(f"[✓] Batch complete: {succeeded} succeeded, {failed} failed")
    log_q.put("__BATCH_DONE__")


def start_batch(
    sources: list[Path],
    target_fmt: str,
    mode: Mode,
    extract_cover: bool,
    log_q: Queue,
) -> threading.Thread:
    """Spawn a daemon thread and start a batch run."""
    t = threading.Thread(
        target=run_batch,
        args=(sources, target_fmt, mode, extract_cover, log_q),
        daemon=True,
    )
    t.start()
    return t

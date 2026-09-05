"""Conversion pipeline orchestrator.

All conversion work runs on a background daemon thread spawned by `start()` or
`start_batch()`. The pipeline posts progress strings to a queue.Queue that the
GUI polls; it never touches Tk widgets directly.

Progress is reported by putting strings on that queue. Control messages are
built exclusively through `markers`, which owns the wire format - see that
module for the full protocol. Nothing here writes a marker string by hand.
"""

import gc
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Literal

from . import assets, from_markdown, hifi, markers, to_markdown

Mode = Literal["standard", "hifi"]


@dataclass
class ConvertParams:
    src: Path
    target_fmt: str          # "pdf" | "docx" | "epub" | "md" | "txt"
    mode: Mode
    extract_cover: bool
    strict_tables: bool = True   # ruled table borders on the PDF path
    dest_dir: Path | None = None  # artifact ROOT; None = beside the source
    keep_intermediates: bool = True


def sanitize_stem(name: str) -> str:
    """Make a filename stem safe for Windows.
    Replaces ':' with '-', collapses whitespace, strips trailing dots, and
    prefixes Windows-reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)."""
    name = name.replace(":", "-")
    name = re.sub(r"\s+", " ", name).strip()
    name = name.strip(". ")
    # COM0 / LPT0 are NOT reserved on Windows - the device names run 1-9.
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", name, re.IGNORECASE):
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


def _claim_base_stem(base: str, claimed: set[str] | None) -> str:
    """Resolve ONE stem for the whole artifact set.

    The three artifacts must stay a coherent sibling set — `{stem}.md` beside
    `{stem}_img/` — because every output generator resolves image references
    against the markdown's parent. Uniquifying them independently yields
    `Book_pdf (1).md` next to `Book_pdf_img (1)`, so the markdown points at
    `Book_pdf (1)_img/` which does not exist. That is the same contract that
    broke weasyprint in v0.2.0 and pandoc silently until v0.3.0.

    It bumps ONLY when another source in the SAME run already claimed the stem.
    Bumping against the filesystem instead would mean re-converting a file
    accumulated `Book_pdf (1).md`, `(2)`, ... on every run, including in the
    default beside-the-source case, which used to overwrite idempotently.
    """
    if claimed is None:
        return base
    candidate, i = base, 1
    while candidate in claimed:
        candidate = f"{base} ({i})"
        i += 1
    claimed.add(candidate)
    return candidate


def _intermediate_paths(
    src: Path,
    dest_dir: Path | None = None,
    claimed: set[str] | None = None,
) -> tuple[str, str, Path, Path, Path]:
    """Compute collision-safe paths for the intermediate artifacts.

    `dest_dir` is the artifact ROOT, not just a home for the final output: the
    markdown, image folder and cover all land under it. None means beside the
    source, which is the pre-v0.4.0 behaviour.

    Stems are suffixed with the source extension so that `Draft.pdf` and
    `Draft.docx` in one folder don't overwrite each other's intermediates. When
    several sources share a destination, `claimed` keeps their sets distinct.

    Returns (stem, src_ext, md_path, img_dir, cover_path).
    """
    src_ext = src.suffix.lower().lstrip(".")
    stem = sanitize_stem(src.stem)
    parent = dest_dir or src.parent
    base_stem = _claim_base_stem(f"{stem}_{src_ext}", claimed)
    md_path = parent / f"{base_stem}.md"
    img_dir = parent / f"{base_stem}_img"
    cover_path = parent / f"{base_stem}_cover.png"
    return stem, src_ext, md_path, img_dir, cover_path


def _cleanup_intermediates(md_path: Path, img_dir: Path, log_q: Queue) -> None:
    """Remove the hub markdown and image folder after a SUCCESSFUL conversion.

    The cover PNG is deliberately kept: the queue panel previews it, so deleting
    it would blank the preview the instant a file finishes.

    Failing to delete a diagnostic artifact must never turn a successful
    conversion into a failed one, so every error here is a logged warning.
    """
    for target in (img_dir, md_path):
        try:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        except OSError as exc:
            log_q.put(f"[!] Could not remove {target.name}: {exc}")


def _run_single(
    params: ConvertParams, log_q: Queue, claimed: set[str] | None = None
) -> Path:
    """Run one conversion. Returns the final output path on success, raises on error.

    Does NOT post completion markers — those are added by the public wrappers
    (`run`, `run_batch`) so batch mode can attach per-file markers.

    Always forces gc.collect() at the end to free PyMuPDF's C-allocated memory.
    """
    src = params.src
    fmt = params.target_fmt.lower()
    stem, src_ext, md_path, img_dir, cover_path_intermediate = _intermediate_paths(
        src, params.dest_dir, claimed
    )
    parent = params.dest_dir or src.parent

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
            except Exception as exc:
                # MS Word missing or COM failed — degrade to Standard
                log_q.put(f"[!] MS Word path unavailable "
                          f"({type(exc).__name__}: {exc}) "
                          f"— falling back to the Standard path (lower fidelity)")
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
            # The hub is still an intermediate here: the bare-stem output above
            # is the deliverable, `{stem}_{ext}.md` is scaffolding.
            if not params.keep_intermediates:
                _cleanup_intermediates(md_path, img_dir, log_q)
            return out_path

        from_markdown.convert(
            md_path, img_dir, cover_path, fmt, out_path, log_q,
            strict_tables=params.strict_tables,
            # A passthrough .md/.txt keeps its images beside the ORIGINAL file,
            # so the source folder has to stay resolvable once the hub is
            # re-rooted into a destination.
            asset_roots=[src.parent],
        )
        # Only now, after the generator returned — on failure these artifacts
        # are the evidence and must survive.
        if not params.keep_intermediates:
            _cleanup_intermediates(md_path, img_dir, log_q)
        log_q.put("[✓] Conversion complete.")
        return out_path
    finally:
        # Free PyMuPDF C-allocated buffers between files — critical for batch runs
        gc.collect()


# ---------------------------------------------------------------------------
# Single-file public API (kept for backward compatibility)
# ---------------------------------------------------------------------------

def run(params: ConvertParams, log_q: Queue) -> None:
    """Single-file conversion. Posts the legacy single-file completion markers."""
    try:
        out_path = _run_single(params, log_q)
        log_q.put(markers.done(out_path))
    except Exception as exc:
        log_q.put(f"[✗] Error: {exc}")
        log_q.put(markers.error())


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
    strict_tables: bool = True,
    cancel: threading.Event | None = None,
    dest_dir: Path | None = None,
    keep_intermediates: bool = True,
) -> None:
    """Process a list of source files sequentially.

    Continues on individual failures. Posts per-file markers and a final
    batch marker when complete; see `markers` for the protocol.

    If `cancel` is supplied, it is checked BETWEEN files. Cancellation is
    deliberately not mid-file: aborting a file in flight would mean abandoning a
    thread that holds PyMuPDF buffers or a live MS Word COM instance, which is
    exactly what the file-lock and CoUninitialize rules exist to prevent. A file
    already being converted therefore finishes before the batch stops, and
    a cancelled marker is posted instead of a completed one.
    """
    # Validate the output root ONCE. Falling back per-file would make the
    # persisted setting non-deterministic - the user would get some files beside
    # the source and some in the chosen folder.
    if dest_dir is not None and not dest_dir.is_dir():
        log_q.put(f"[✗] Output folder is unavailable: {dest_dir}")
        log_q.put("[✗] Batch aborted — choose an output folder that exists.")
        log_q.put(markers.batch_done())
        return

    succeeded = failed = 0
    total = len(sources)
    # Keeps two same-named sources from different folders from overwriting each
    # other's artifacts when they share one destination.
    claimed: set[str] = set()

    for i, src in enumerate(sources):
        if cancel is not None and cancel.is_set():
            log_q.put(
                f"[!] Cancelled: {succeeded} converted, {failed} failed, "
                f"{total - i} not started"
            )
            log_q.put(markers.batch_cancelled())
            return

        log_q.put(markers.file_start(i))
        log_q.put(f"[*] === ({i + 1}/{total}) {src.name} ===")
        params = ConvertParams(
            src=src,
            target_fmt=target_fmt,
            mode=mode,
            extract_cover=extract_cover,
            strict_tables=strict_tables,
            dest_dir=dest_dir,
            keep_intermediates=keep_intermediates,
        )
        try:
            _run_single(params, log_q, claimed)
            log_q.put(markers.file_done(i))
            succeeded += 1
        except Exception as exc:
            log_q.put(f"[✗] {src.name}: {exc}")
            # The reason travels with the marker so the GUI can show it on the
            # row; the full text also stays in the log above.
            log_q.put(markers.file_error(i, f"{type(exc).__name__}: {exc}"))
            failed += 1

    log_q.put(f"[✓] Batch complete: {succeeded} succeeded, {failed} failed")
    log_q.put(markers.batch_done())


def start_batch(
    sources: list[Path],
    target_fmt: str,
    mode: Mode,
    extract_cover: bool,
    log_q: Queue,
    strict_tables: bool = True,
    cancel: threading.Event | None = None,
    dest_dir: Path | None = None,
    keep_intermediates: bool = True,
) -> threading.Thread:
    """Spawn a daemon thread and start a batch run."""
    t = threading.Thread(
        target=run_batch,
        args=(sources, target_fmt, mode, extract_cover, log_q, strict_tables,
              cancel, dest_dir, keep_intermediates),
        daemon=True,
    )
    t.start()
    return t

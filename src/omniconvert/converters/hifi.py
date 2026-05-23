"""High-fidelity conversion paths that bypass the Markdown hub.

These functions preserve exact layout / formatting by using format-specific
libraries instead of routing through Markdown. Always called from the
pipeline's daemon thread (NOT the main GUI thread).
"""

from pathlib import Path
from queue import Queue


def pdf_to_docx(src: Path, out: Path, log_q: Queue) -> None:
    """Layout-preserving PDF → DOCX via pdf2docx.
    cv.close() is called before this function returns so the caller
    can safely open the same PDF with PyMuPDF afterwards."""
    from pdf2docx import Converter

    log_q.put("[*] Running High-Fidelity layout conversion (pdf2docx)...")
    cv = Converter(str(src))
    try:
        cv.convert(str(out))
        log_q.put(f"[✓] Done: {out.name}")
    finally:
        cv.close()  # always release file handle before returning


def docx_to_pdf(src: Path, out: Path, log_q: Queue) -> None:
    """Layout-preserving DOCX → PDF via Microsoft Word COM (docx2pdf).

    Requires MS Word installed on Windows. Raises ImportError / com_error
    if Word is missing — the pipeline catches and falls back to Standard mode.

    Wraps the COM call in CoInitialize/CoUninitialize because this runs on
    a daemon thread, not the main thread (COM is per-thread on Windows).
    Without this, the first call crashes with:
        pywintypes.com_error: CoInitialize has not been called.
    """
    import pythoncom  # ships with pywin32 (pulled in transitively by docx2pdf)
    from docx2pdf import convert

    pythoncom.CoInitialize()
    try:
        log_q.put("[*] Running High-Fidelity conversion (Microsoft Word COM)...")
        convert(str(src), str(out))
        log_q.put(f"[✓] Done: {out.name}")
    finally:
        pythoncom.CoUninitialize()  # prevents WINWORD.EXE zombie leak

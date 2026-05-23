# Changelog

All notable changes to OmniConvert are documented here.

## [0.2.0] — 2026-05-22

### Added
- **Native drag-and-drop** — drop one or many files (or a folder) onto the OmniConvert window to queue them. Visual hover feedback (blue "Drop to load…" indicator) confirms the drop target is active.
- **Batch conversion** — a scrollable queue panel on the left shows every file with status icons (`○` pending, `▶` running, `✓` done, `✗` error). Click any row to preview that file's cover. Convert button label adapts (`Convert` / `Convert Batch (N)`).
- **"Add Folder…" button** — pick a folder, OmniConvert scans it for supported files. Companion "Include subfolders" checkbox enables recursive scans.
- **"Browse Files…" button** — multi-select file picker (replaces the single-file Browse button).
- **DOCX → PDF High-Fidelity path** — uses Microsoft Word via COM (`docx2pdf`) for flawless layout preservation. Falls back to weasyprint silently if Word is unavailable.
- Sequential batch execution on the daemon thread with continue-on-error and a final `[✓] Batch complete: N succeeded, M failed` summary.
- `gc.collect()` between batch iterations to release PyMuPDF's C-allocated buffers (prevents OOM on large batches).
- Active row gets a yellow-tinted background while running; user-selected row gets a blue-tinted background. Selecting the currently-running row re-arms auto-tracking.

### Changed
- **File collision guard** — intermediate artifacts now suffix the source extension (`Draft.pdf` → `Draft_pdf.md`, `Draft_pdf_img/`, `Draft_pdf_cover.png`). `Draft.pdf` and `Draft.docx` in the same folder no longer overwrite each other's intermediates.
- **Final output collision guard** — if `Draft.docx` already exists, output goes to `Draft (1).docx`, `Draft (2).docx`, etc.
- **WeasyPrint base_url** — fixed double-nesting bug. Image references inside the markdown already include the img-folder name; base_url is now always `md_path.parent`.
- High-Fidelity mode segmented button is enabled for both PDF↔DOCX directions (was PDF→DOCX only).
- Window grew from 960×680 to 960×720 to accommodate the queue panel.

### Fixed
- COM threading crash in `docx2pdf` — wrapped in `pythoncom.CoInitialize/CoUninitialize` so the daemon thread can drive MS Word without `CoInitialize has not been called` errors, and without leaking zombie `WINWORD.EXE` processes.
- Mid-flight input race — drops / browse / folder-add are rejected during an active batch (logged, no state corruption).

## [0.1.0] — 2026-05-22

### Added
- Initial release
- CustomTkinter GUI (960×680, dark mode) with cover preview panel and real-time log
- Hub-and-spoke conversion architecture using Markdown as the universal intermediate format
- **Standard mode** — all 20 format pairs (PDF, DOCX, EPUB, MD, TXT)
  - PDF → Markdown via `pymupdf4llm` (column-aware, image-preserving)
  - DOCX → Markdown via `markitdown`
  - EPUB → Markdown via `ebooklib` + `html2text`
  - Markdown → PDF via `weasyprint` (no pandoc required)
  - Markdown → DOCX / EPUB / TXT via `pypandoc`
- **High-Fidelity mode** — layout-preserving PDF → DOCX via `pdf2docx`
- Cover art extraction for PDF, DOCX, and EPUB sources
- Full inline image extraction and re-embedding in all output formats
- Portable pandoc installer (`scripts/install_pandoc.py`) — no admin rights required
- Amber warning banner when pandoc is not detected; affected targets disabled
- Windows path sanitization (`sanitize_stem`) — handles colons, reserved names, whitespace
- `ebooklib` UserWarning suppression to keep log output clean

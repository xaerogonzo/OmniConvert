# Changelog

All notable changes to OmniConvert are documented here.

## [0.4.0] — 2026-08-30

### Added
- **Choose where output goes.** "Output to…" sets an output *root*: the converted
  file, the hub `.md`, the `_img/` folder and the cover all land there together.
  Leaving it unset keeps the v0.3 behaviour of writing beside each source. This
  also makes read-only and network sources convertible.
- **"Keep intermediate files" option.** On by default. Turning it off deletes the
  hub markdown and image folder after a *successful* conversion, so a 50-file
  batch stops leaving 150 extra files among the originals. The cover is always
  kept — the queue panel previews it. Cleanup failures are logged as warnings and
  never turn a successful conversion into a failed one.
- **Per-row remove.** Each queue row has a `✕`. Refused while a batch is running,
  because worker progress is reported by position and removing a row would shift
  every later index onto the wrong file.
- **Failure reasons on the row.** A failed file shows why in place, clipped to one
  line, with the full text still in the log. Previously the only way to find out
  was scrolling the log.
- **Retry Failed.** Re-runs only the failed rows, leaving completed ones alone.
  Repeatable while failures remain. Cancelled-but-unstarted files stay `pending`
  rather than `error`, so retry correctly skips them.
- **Session memory.** Target format, mode, all four options, output destination
  and window geometry persist to `%LOCALAPPDATA%/OmniConvert/settings.json`. The
  file is versioned and tolerated field-by-field: one corrupt value resets that
  value alone, and a missing, unreadable, malformed or future-version file starts
  the app on defaults rather than failing.

### Changed
- **The GUI↔worker protocol has one definition.** New
  `converters/markers.py` owns the wire format with a single serializer and a
  single parser; `pipeline.py` and `app.py` no longer restate marker strings.
  `parse()` is a trust boundary — malformed worker messages degrade to log text
  instead of raising into the poll loop.
- Format vocabulary moved to a Tk-free `omniconvert/formats.py` so settings
  validation can share it without importing CustomTkinter; `ui/constants.py`
  re-exports it.
- Toolbar extracted to `ui/toolbar_panel.py`, which owns the queue summary, the
  drag hint and the destination display.
- The conversion mode is persisted as the user's *preference*. An empty queue
  forces the live mode to Standard, which previously overwrote a saved
  High-Fidelity choice on every launch.

### Fixed
- **Passthrough sources lost their images when re-rooted.** Converting a `.md`
  into a different output folder moved the hub but not the images beside the
  original, so every reference broke. Generators now resolve against several
  asset roots — the markdown's parent first, then the source's.
- **A shared destination could make two sources overwrite each other.** Two
  `Book.pdf` from different folders produced identical artifact names once they
  were no longer separated by their parent directories. Stems are now claimed per
  run, as a coherent set: `Book_pdf (1).md` comes with `Book_pdf (1)_img/`, never
  a mismatched pair. Re-running one file still overwrites its own artifacts
  rather than accumulating `(1)`, `(2)`, …
- `Open Folder` opened the source's directory unconditionally, which stopped
  being the output folder once a destination could be set. It, the cover preview
  and open-cover now all derive from one resolver.
- A corrupt saved window geometry could stop the app from starting: CustomTkinter
  parses the string itself and raises `TypeError` from its scaling code, not the
  `tk.TclError` a guard would expect.

## [0.3.0] — 2026-08-30

### Added
- **Cancel a running batch** — the Convert button becomes Cancel while a batch is
  active. Cancellation is checked *between* files: the file currently converting
  finishes first, because abandoning it mid-flight would strand PyMuPDF buffers
  or a live MS Word COM instance. Logs `[!] Cancelled: N converted, M failed,
  K not started`.
- **Overall progress bar** above the Convert button, driven by the existing
  per-file markers.
- **"Clear" and "Open Folder" buttons** in the toolbar.
- **Test suite** — 91 tests under `tests/`, all headless. Covers the path
  helpers, converter dispatch, the DOCX image path, the PDF renderer, batch
  orchestration and cancellation, the queue model, and a window-construction
  smoke test. Run with `python -m pytest`.
- `requirements-dev.txt` for the test dependencies.

### Changed
- **The queue now accumulates instead of being replaced.** Dropping or browsing
  appends to the existing queue and skips files already present (deduplicated on
  resolved path, case-insensitively). Use Clear to empty it.
- **MD → PDF now renders with PyMuPDF's Story engine instead of weasyprint.**
  weasyprint requires the GTK/Pango DLLs on Windows, which cannot be bundled into
  the Nuitka one-file build — meaning `OmniConvert.exe` could never produce a PDF
  on a machine that lacked them, and PDF output failed outright wherever GTK was
  absent. PyMuPDF is already a dependency, needs no system libraries, and renders
  identically everywhere. Trade-off: the text column is now set by the page
  geometry rather than `max-width`, and `page-break-after: avoid` on headings is
  no longer honoured.
- **`weasyprint` removed from `requirements.txt`**; `mammoth` and `pymupdf` added
  as explicit direct dependencies. All dependencies are now version-pinned.
- **`app.py` split into an `omniconvert.ui` package** — `queue_model.py` (Tk-free
  queue state), `queue_panel.py`, `controls_panel.py`, `log_panel.py` and
  `constants.py`. `app.py` shrank from 686 to 489 lines and now owns only the
  root window, drop bindings, pipeline handoff and log dispatch.
- The `_{stem}_{ext}_cover.png` naming convention is now derived from
  `pipeline._intermediate_paths()` rather than re-implemented in the GUI.
- **The Nuitka build now produces a working executable.** Three faults, all
  pre-existing and inherited from the build template, meant `OmniConvert.exe` had
  been broken since v0.2.0:
  - `numpy` and `pandas` were on the `--nofollow-import-to` exclusion list while
    being genuinely required (`pdf2docx` reaches numpy through `cv2`; `markitdown`
    imports pandas at module load). The exe raised `ImportError` on **every DOCX
    source** and on **High-Fidelity PDF -> DOCX**. Both are now bundled.
  - `sympy` was *not* excluded, though nothing uses it - it is reached only via
    `pdf2docx` -> `fontTools` -> `fontTools.misc.symfont`. Nuitka compiled all
    ~1000 of its modules: 5958 object files, 3.2 GB, and a build that stalled
    before linking. Now excluded.
  - `build.ps1` is UTF-8 without a BOM and contained two em-dashes, but
    `build.bat` runs it under Windows PowerShell 5.1, which decodes BOM-less
    files as cp1252. The em-dash became three characters ending in U+201D, which
    PowerShell honours as a string delimiter, so the script failed to parse. The
    script is now pure ASCII, and `build.bat` propagates the exit code instead of
    always returning 0 - which is why the parse failure previously looked like a
    successful build.
- Removed `--include-package=pystray` from the Nuitka build — it was never
  imported by OmniConvert and only added bulk to the exe.

### Fixed
- **DOCX sources lost every inline image.** `markitdown` delegates to `mammoth`,
  whose default handler inlines images as base64 data URIs — so the hub markdown
  ballooned by ~33% and no `_img/` folder was ever created. `_from_docx` now
  drives mammoth directly with its own image handler, writing real files to
  `{stem}_docx_img/` and emitting URL-encoded relative references. Word equations
  still become LaTeX via markitdown's OMML pre-pass.
- **Pandoc output silently dropped every image, for all source formats.**
  `--resource-path` pointed at the image folder, but markdown references already
  contain the folder name, so pandoc looked for `img_dir/img_dir/x.png`. It now
  points at the markdown's parent directory — the same rule the PDF path follows.
  This affected EPUB and DOCX output from PDF and EPUB sources too, not just DOCX.
- **"Preserve Headers" and "Strict Table Grid" did nothing.** Both were
  pre-selected and read by no code. "Strict Table Grid" is now wired to the PDF
  table CSS (ruled borders and a shaded header band when on, borderless when
  off). "Preserve Headers" was removed — every parser preserves headings
  unconditionally, so there was no behaviour for it to select.
- `sanitize_stem()` prefixed `COM0` and `LPT0`, which Windows does not reserve.
  The device names run 1–9, as the docstring always claimed.
- `__version__` said `0.1.0` while the changelog was at 0.2.0.
- The High-Fidelity DOCX → PDF fallback caught `(ImportError, Exception)` — a
  redundant tuple that reported every bug as "MS Word unavailable". It now
  catches `Exception` and logs the actual message.
- Queue rows no longer raise if a file is deleted between queueing and rendering.

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

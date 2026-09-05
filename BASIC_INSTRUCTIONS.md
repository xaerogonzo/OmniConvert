# OmniConvert — Basic Instructions

@D:/Claude Co worker/Token Save Manager Source/templates\project-baseline.md

---

## Project Overview

**Name:** OmniConvert  
**Stack:** Python 3.13, CustomTkinter, pymupdf4llm/pymupdf, markitdown, mammoth, ebooklib, pypandoc, pdf2docx, Pillow  
**Entry point:** `main.py` (`python main.py`)  
**Purpose:** Zero-bloat offline desktop document converter — converts PDF, DOCX, EPUB, MD, and TXT bidirectionally with full image/cover preservation.

---

## Project Structure

```
D:\Random Projects\File Converter\
├── src/
│   └── omniconvert/            # Main application package
│       ├── __init__.py         # Version: 0.3.0
│       ├── app.py              # Root window, DnD, pipeline handoff, log dispatch
│       ├── converters/
│       │   ├── __init__.py
│       │   ├── pipeline.py     # Hub-and-spoke orchestrator + sanitize_stem + cancel
│       │   ├── to_markdown.py  # All input parsers → Markdown
│       │   ├── from_markdown.py# Markdown → all output formats
│       │   ├── hifi.py         # High-fidelity PDF → DOCX via pdf2docx
│       │   └── assets.py       # Cover image extraction (PDF/DOCX/EPUB)
│       └── ui/
│           ├── constants.py    # Formats, status icons, row colours
│           ├── queue_model.py  # Tk-free queue state (add/dedup/select/status)
│           ├── queue_panel.py  # Cover preview + scrollable queue rows
│           ├── controls_panel.py # Format, mode, options, progress, convert
│           └── log_panel.py    # Log textbox
├── scripts/
│   └── install_pandoc.py       # One-time portable pandoc downloader
├── docs/
│   ├── ARCHITECTURE.md         # System design and data flow
│   ├── DEVELOPMENT.md          # Setup, build, and extension guide
│   └── CHANGELOG.md            # Version history
├── tests/                      # pytest suite (headless; run: python -m pytest)
├── vendor/
│   └── pandoc/                 # Portable pandoc (after running install script)
│       └── pandoc.exe
├── dist/                       # Nuitka build output (gitignored)
├── .gitignore
├── README.md                   # Project overview and quick start
├── BASIC_INSTRUCTIONS.md       # This file
├── requirements.txt            # Python dependencies (version-pinned)
├── requirements-dev.txt        # Test dependencies
├── main.py                     # Entry point shim (adds src/ to sys.path)
├── build.ps1                   # Nuitka one-file build pipeline
└── build.bat                   # Launcher for build.ps1
```

---

## Documentation Files

| File | Location | Purpose |
|---|---|---|
| Basic Instructions | `BASIC_INSTRUCTIONS.md` | This file — project conventions and rules |
| README | `README.md` | Project overview, quick start, format matrix |
| Architecture | `docs/ARCHITECTURE.md` | System design, data flow, library map |
| Development | `docs/DEVELOPMENT.md` | Setup, build, and extension guide |
| Changelog | `docs/CHANGELOG.md` | Version history |
| Requirements | `requirements.txt` | Python pip dependencies (pinned) |
| Dev requirements | `requirements-dev.txt` | pytest + fixture generation |

---

## Architecture

**Hub-and-Spoke:** Every format is first converted to Markdown (the hub), then Markdown is compiled to the target format. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full diagram.

- **Standard mode:** pymupdf4llm (PDF→MD), mammoth+markitdown (DOCX→MD), ebooklib+html2text (EPUB→MD); pymupdf Story for MD→PDF, pandoc for MD→DOCX/EPUB/TXT
- **High-Fidelity mode:** pdf2docx bypasses the hub for PDF→DOCX, preserving exact column layout and image positions

**Asset isolation:** Cover images extracted to `{stem}_cover.png`; inline images to `{stem}_img/`; intermediate Markdown kept as `{stem}.md` — all in the source file's folder.

---

## Key Files

- `main.py` — thin entry shim; inserts `src/` into `sys.path` then launches `OmniConvertApp`
- `src/omniconvert/app.py` — root window, drop bindings, pipeline handoff, `_poll_log` marker dispatch. The panels live in `src/omniconvert/ui/`
- `src/omniconvert/ui/queue_model.py` — Tk-free queue state; the place to add queue behaviour so it stays testable
- `src/omniconvert/converters/pipeline.py` — `start()` spawns daemon thread; `sanitize_stem()` handles Windows path edge cases
- `src/omniconvert/converters/assets.py` — cover extraction; called strictly AFTER pdf2docx closes its file handle
- `src/omniconvert/converters/from_markdown.py` — pymupdf Story is the PRIMARY MD→PDF engine (no pandoc, no system libraries)

---

## Project-Specific Rules

- **ebooklib warnings**: Both `to_markdown.py` and `from_markdown.py` suppress ebooklib's UserWarnings at the top of the file — do not remove these filters.
- **Threading**: The `Convert` button must only spawn `threading.Thread(daemon=True)` — never call `pipeline.run()` on the main thread or the GUI freezes.
- **File locking**: `hifi.pdf_to_docx()` always calls `cv.close()` before returning; `assets.extract_cover()` is called only after that function returns.
- **Pandoc**: Required for DOCX/EPUB/TXT output in Standard mode. PDF output uses pymupdf natively. High-Fidelity PDF→DOCX uses pdf2docx — no pandoc needed.
- **No system libraries, ever.** weasyprint was removed in v0.3.0 because it needs the GTK/Pango DLLs, which Nuitka cannot bundle — the built .exe could not make PDFs on a clean machine. Do not reintroduce a dependency that needs a system-wide install.
- **Image reference contract**: parsers emit refs that ALREADY contain the img-folder name. Output generators resolve them against `md_path.parent` — `archive=` for pymupdf, `--resource-path=` for pandoc. Never point either at `img_dir`; it resolves one level too deep and images vanish silently.
- **DOCX images**: `_from_docx` drives mammoth directly with a custom `convert_image` handler. Do not fall back to plain `MarkItDown().convert()` — mammoth's default handler inlines base64 data URIs and leaves `_img/` empty.
- **`dest_dir` is the artifact ROOT**, not just where the final file goes: output, hub `.md`, `_img/` and cover move together, or image references break. Collision stems are claimed per-run so re-runs stay idempotent.
- **Cancellation is between files, never mid-file.** Aborting in flight would strand PyMuPDF buffers or a live Word COM instance.
- **Build config**: `build.ps1` must stay pure ASCII (PowerShell 5.1 reads it as
  cp1252). Never exclude `numpy`/`pandas`/`cv2` from the Nuitka flags - they are
  transitive but required. Always keep `sympy` excluded. Verify a build by
  actually running `dist/OmniConvert.exe`, not just by it compiling.
- **Marker protocol**: `converters/markers.py` is the ONLY place the GUI<->worker
  wire format is written or read. Never add a raw `__MARKER__` string elsewhere.
  `parse()` must keep returning None for malformed input rather than raising.
- **Settings**: versioned and tolerated field-by-field; one bad value resets that
  value alone, and `load()` must never stop the app starting. `config_path()`
  must never derive from `__file__` - a frozen exe cannot write to its install
  directory.
- **Tests**: `python -m pytest`. Keep new queue/pipeline logic Tk-free so it stays coverable; GUI tests share one Tk root per module.
- **Path safety**: Use `pathlib.Path` everywhere. `sanitize_stem()` in `pipeline.py` replaces `:` with `-` and collapses whitespace.
- **Imports**: Inside the `omniconvert` package, use absolute imports from the package root: `from omniconvert.converters.pipeline import ...`. Within `converters/` submodules, relative imports (`from . import ...`) are fine.

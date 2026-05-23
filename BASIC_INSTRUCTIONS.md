# OmniConvert — Basic Instructions

@D:/Claude Co worker/Token Save Manager Source/templates\project-baseline.md

---

## Project Overview

**Name:** OmniConvert  
**Stack:** Python 3.13, CustomTkinter, pymupdf4llm, markitdown, ebooklib, weasyprint, pypandoc, pdf2docx, Pillow  
**Entry point:** `main.py` (`python main.py`)  
**Purpose:** Zero-bloat offline desktop document converter — converts PDF, DOCX, EPUB, MD, and TXT bidirectionally with full image/cover preservation.

---

## Project Structure

```
D:\Random Projects\File Converter\
├── src/
│   └── omniconvert/            # Main application package
│       ├── __init__.py         # Version: 0.1.0
│       ├── app.py              # CustomTkinter GUI (960×680, dark mode)
│       └── converters/
│           ├── __init__.py
│           ├── pipeline.py     # Hub-and-spoke orchestrator + sanitize_stem
│           ├── to_markdown.py  # All input parsers → Markdown
│           ├── from_markdown.py# Markdown → all output formats
│           ├── hifi.py         # High-fidelity PDF → DOCX via pdf2docx
│           └── assets.py       # Cover image extraction (PDF/DOCX/EPUB)
├── scripts/
│   └── install_pandoc.py       # One-time portable pandoc downloader
├── docs/
│   ├── ARCHITECTURE.md         # System design and data flow
│   ├── DEVELOPMENT.md          # Setup, build, and extension guide
│   └── CHANGELOG.md            # Version history
├── tests/                      # Test suite (future)
├── vendor/
│   └── pandoc/                 # Portable pandoc (after running install script)
│       └── pandoc.exe
├── dist/                       # Nuitka build output (gitignored)
├── .gitignore
├── README.md                   # Project overview and quick start
├── BASIC_INSTRUCTIONS.md       # This file
├── requirements.txt            # Python dependencies
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
| Requirements | `requirements.txt` | Python pip dependencies |

---

## Architecture

**Hub-and-Spoke:** Every format is first converted to Markdown (the hub), then Markdown is compiled to the target format. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full diagram.

- **Standard mode:** pymupdf4llm (PDF→MD), markitdown (DOCX→MD), ebooklib+html2text (EPUB→MD); weasyprint for MD→PDF, pandoc for MD→DOCX/EPUB/TXT
- **High-Fidelity mode:** pdf2docx bypasses the hub for PDF→DOCX, preserving exact column layout and image positions

**Asset isolation:** Cover images extracted to `{stem}_cover.png`; inline images to `{stem}_img/`; intermediate Markdown kept as `{stem}.md` — all in the source file's folder.

---

## Key Files

- `main.py` — thin entry shim; inserts `src/` into `sys.path` then launches `OmniConvertApp`
- `src/omniconvert/app.py` — GUI: pandoc banner, file picker, cover preview panel, format/mode controls, log textbox
- `src/omniconvert/converters/pipeline.py` — `start()` spawns daemon thread; `sanitize_stem()` handles Windows path edge cases
- `src/omniconvert/converters/assets.py` — cover extraction; called strictly AFTER pdf2docx closes its file handle
- `src/omniconvert/converters/from_markdown.py` — weasyprint is the PRIMARY MD→PDF engine (no pandoc needed for PDF output)

---

## Project-Specific Rules

- **ebooklib warnings**: Both `to_markdown.py` and `from_markdown.py` suppress ebooklib's UserWarnings at the top of the file — do not remove these filters.
- **Threading**: The `Convert` button must only spawn `threading.Thread(daemon=True)` — never call `pipeline.run()` on the main thread or the GUI freezes.
- **File locking**: `hifi.pdf_to_docx()` always calls `cv.close()` before returning; `assets.extract_cover()` is called only after that function returns.
- **Pandoc**: Required for DOCX/EPUB/TXT output in Standard mode. PDF output uses weasyprint natively. High-Fidelity PDF→DOCX uses pdf2docx — no pandoc needed.
- **Path safety**: Use `pathlib.Path` everywhere. `sanitize_stem()` in `pipeline.py` replaces `:` with `-` and collapses whitespace.
- **Imports**: Inside the `omniconvert` package, use absolute imports from the package root: `from omniconvert.converters.pipeline import ...`. Within `converters/` submodules, relative imports (`from . import ...`) are fine.

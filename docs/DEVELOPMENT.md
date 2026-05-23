# Development Guide

## Prerequisites

- Python 3.11+ (project uses 3.13)
- pip
- Windows 10/11 (GUI uses tkinter which is pre-installed with Python on Windows)

## First-Time Setup

```bash
# Clone / open the project folder, then:

# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install portable pandoc (writes vendor/pandoc/pandoc.exe)
python scripts/install_pandoc.py

# 3. Launch
python main.py
```

## Running Without Pandoc

PDF output and High-Fidelity PDF → DOCX work without pandoc. The app shows an amber warning banner for the disabled targets (DOCX, EPUB, TXT in Standard mode). This is expected during development before running `install_pandoc.py`.

## Project Layout

```
src/
  omniconvert/
    __init__.py             Package version
    app.py                  CustomTkinter GUI (960x680, dark mode)
    converters/
      __init__.py
      pipeline.py           Orchestrator — mode routing, sanitize_stem, thread spawn
      to_markdown.py        All input parsers → Markdown
      from_markdown.py      All output generators from Markdown
      hifi.py               High-fidelity PDF → DOCX via pdf2docx
      assets.py             Cover image extraction (PDF / DOCX / EPUB)

scripts/
  install_pandoc.py         One-time portable pandoc downloader

docs/
  ARCHITECTURE.md           System design and data flow
  DEVELOPMENT.md            This file
  CHANGELOG.md              Version history

tests/                      Test suite (future)
vendor/pandoc/              Portable pandoc binary (after running install script)
dist/                       Nuitka build output (gitignored)
```

## Key Entry Points

| Command | Purpose |
|---------|---------|
| `python main.py` | Launch the GUI |
| `python scripts/install_pandoc.py` | Download portable pandoc |
| `.\build.bat` | Compile to `dist\OmniConvert.exe` via Nuitka |

## Adding a New Input Format

1. Add a `_from_{fmt}` function in `src/omniconvert/converters/to_markdown.py`
2. Add the new extension to the `convert()` dispatcher
3. Add it to `SUPPORTED` in `src/omniconvert/app.py`
4. Add it to the `filetypes` list in `_browse_file()`

## Adding a New Output Format

1. Add a case in `src/omniconvert/converters/from_markdown.py::convert()`
2. Add the format string to `FORMATS` in `src/omniconvert/app.py`

## Build (Nuitka)

Produces a single portable `.exe` — no Python install required on the target machine.

```powershell
.\build.bat
# Output: dist\OmniConvert.exe
```

Requirements before building:
```bash
pip install nuitka ordered-set zstandard
```

See `build.ps1` for the full flag list. Key flags already configured:
- `--enable-plugin=tk-inter` — bundles tkinter
- `--include-package=customtkinter`, `pymupdf`, `markitdown`, `ebooklib`, `pdf2docx`, `weasyprint`
- `--nofollow-import-to=numpy,scipy,pandas,...` — excludes Anaconda scientific stack

## ebooklib Warnings

ebooklib emits aggressive `UserWarning` messages about future deprecations. These are suppressed at the top of both `to_markdown.py` and `from_markdown.py`:

```python
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")
```

Do not remove these — they would flood the GUI log textbox.

## Threading Rules

- **Convert button** → only ever spawns `threading.Thread(daemon=True)`. Never calls `pipeline.run()` on the main thread.
- **pipeline.run()** → posts strings to `queue.Queue`. Never touches tkinter widgets directly.
- **_poll_log()** → called via `self.after(100, ...)` on the main thread. Drains the queue and updates widgets.

## File Lock Rule (High-Fidelity Mode)

`hifi.pdf_to_docx()` always calls `cv.close()` before returning. `assets.extract_cover()` is called by `pipeline.py` only after `pdf_to_docx()` returns. Both tools open the same PDF; interleaving them causes a `PermissionError` on Windows.

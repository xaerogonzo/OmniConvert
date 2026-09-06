# Development Guide

## Prerequisites

- Python 3.11+ (project uses 3.13)
- pip
- Windows 10/11 (GUI uses tkinter which is pre-installed with Python on Windows)

## First-Time Setup

Use a project virtualenv. `requirements.txt` pins exact versions, and those
pins are only meaningful in an environment OmniConvert controls - installing
into a shared conda base means some other project's constraints silently win.
That has already bitten once: the pytest pin read 8.4.2 while 9.0.3 was what
actually ran.

```bash
# Clone / open the project folder, then:

# 1. Create an isolated environment and install dependencies
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt

# (equivalently, without a venv - not recommended)
pip install -r requirements.txt

# 2. Install portable pandoc (writes vendor/pandoc/pandoc.exe)
python scripts/install_pandoc.py

# 3. Launch
python main.py
```

## Testing

```bash
.venv/Scripts/python -m pytest
```

The whole suite is headless and takes a few seconds. Fixtures (DOCX, PNG) are
*generated* at test time rather than committed, so they cannot drift from the
libraries that produce them. `tests/test_gui_smoke.py` does build the real
window; it shares one Tk root across the module (Tk tolerates only one per
process) and skips cleanly where no display is available.

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
    formats.py              Tk-free format vocabulary (shared with settings)
    settings.py             Versioned, field-tolerant preference persistence
    converters/
      markers.py            The GUI<->worker wire protocol (one serializer/parser)
    ui/
      __init__.py
      constants.py          Status icons, row colours; re-exports formats
      queue_model.py        Tk-free queue state (add/dedup/select/status/errors)
      queue_panel.py        Cover preview + scrollable queue rows
      controls_panel.py     Format, mode, options, progress, convert, retry
      toolbar_panel.py      Queue actions, queue summary, output destination
      log_panel.py          Log textbox

scripts/
  install_pandoc.py         One-time portable pandoc downloader

docs/
  ARCHITECTURE.md           System design and data flow
  DEVELOPMENT.md            This file
  CHANGELOG.md              Version history

tests/                      Test suite (pytest)
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
3. Add it to `SUPPORTED` in `src/omniconvert/ui/constants.py`
4. Add it to the `filetypes` list in `_browse_file()`

## Adding a New Output Format

1. Add a case in `src/omniconvert/converters/from_markdown.py::convert()`
2. Add the format string to `FORMATS` in `src/omniconvert/ui/constants.py`
3. If it needs pandoc, add it to `PANDOC_TARGETS` there too

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

**Build rules that are easy to break** (see docs/ARCHITECTURE.md for the full
reasoning):

- `build.ps1` must stay **pure ASCII**. `build.bat` runs it under Windows
  PowerShell 5.1, which reads BOM-less files as cp1252; a stray non-ASCII
  character decodes into a smart quote and silently breaks parsing.
- Never add `numpy`, `pandas` or `cv2` to `--nofollow-import-to`. They arrive
  transitively but are required at runtime; excluding them yields an exe that
  fails on DOCX and on High-Fidelity PDF -> DOCX.
- Keep `sympy` excluded, or the build compiles ~1000 unused modules and stalls.
- If a build exceeds ~2 GB under `dist/` or stops writing files for several
  minutes, stop it and check which package is being compiled rather than waiting.

See `build.ps1` for the full flag list. Key flags already configured:
- `--enable-plugin=tk-inter` — bundles tkinter
- `--include-package=customtkinter`, `pymupdf`, `markitdown`, `mammoth`, `ebooklib`, `pdf2docx`
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
- **Cancellation** → `run_batch` checks a `threading.Event` between files only. Never abort a file in flight: it would strand PyMuPDF buffers or a live Word COM instance, defeating the file-lock and `CoUninitialize` rules.

## File Lock Rule (High-Fidelity Mode)

`hifi.pdf_to_docx()` always calls `cv.close()` before returning. `assets.extract_cover()` is called by `pipeline.py` only after `pdf_to_docx()` returns. Both tools open the same PDF; interleaving them causes a `PermissionError` on Windows.

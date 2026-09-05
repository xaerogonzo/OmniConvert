# OmniConvert

Zero-bloat, fully offline desktop document converter. Converts between PDF, DOCX, EPUB, Markdown, and plain text — bidirectionally — with full image and cover art preservation.

## Quick Start

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install portable pandoc (needed for DOCX / EPUB / TXT output)
python scripts/install_pandoc.py

# 3. Launch the app
python main.py
```

Run the tests with:

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Supported Formats

| | PDF | DOCX | EPUB | MD | TXT |
|---|:---:|:---:|:---:|:---:|:---:|
| **PDF** | — | ✓ | ✓ | ✓ | ✓ |
| **DOCX** | ✓ | — | ✓ | ✓ | ✓ |
| **EPUB** | ✓ | ✓ | — | ✓ | ✓ |
| **MD** | ✓ | ✓ | ✓ | — | ✓ |
| **TXT** | ✓ | ✓ | ✓ | ✓ | — |

## Conversion Modes

**Standard** — Hub-and-spoke through Markdown. Preserves text structure, headings, tables, and all inline images. Works for all 20 format pairs. PDF output is rendered by PyMuPDF and needs no pandoc; DOCX / EPUB / TXT output needs the portable pandoc.

**High-Fidelity** — Layout-preserving paths that bypass the Markdown hub:
- **PDF → DOCX** via `pdf2docx` (no pandoc required)
- **DOCX → PDF** via Microsoft Word COM (`docx2pdf`) when Word is installed; falls back to weasyprint otherwise

## Features

- Dark-mode CustomTkinter GUI with cover art preview
- **Drag-and-drop** — drop one or many files (or a folder) onto the window to queue them
- **Batch conversion** — scrollable queue with per-file status icons; convert dozens of files in one click
- **"Add Folder…"** — recursive scan option for deep folder hierarchies
- All inline images extracted and re-embedded in the output
- Portable pandoc — no system-wide install, no admin rights
- **Choose an output folder**, or leave outputs beside each source (the default)
- **Discard intermediates** after conversion, or keep them for AI pipelines
- **Remove single files** from the queue, see why one failed, and retry just the failures
- **Remembers your settings** between launches
- **Cancel** a running batch at any point — the current file finishes, the rest are skipped
- Live progress bar and per-file status icons
- Intermediate Markdown files kept on disk (AI pipeline friendly)
- Windows path safety — handles colons, reserved names, and same-stem collisions across formats
- No system libraries required — everything ships in the wheel or the vendored pandoc

## Building a Standalone Executable

```powershell
.\build.bat
```

Produces `dist\OmniConvert.exe` via Nuitka — no Python install required to run.

## Project Layout

```
src/omniconvert/    Core application package
scripts/            Setup and utility scripts
docs/               Architecture and development docs
tests/              Test suite (pytest, headless)
vendor/pandoc/      Portable pandoc binary (after running install_pandoc.py)
dist/               Nuitka build output (gitignored)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full system design.

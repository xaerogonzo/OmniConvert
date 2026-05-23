# Architecture

## Overview

OmniConvert is a single-process Python desktop application. The GUI runs on the main thread; all conversion work runs on a daemon background thread. A `queue.Queue` bridges the two — the pipeline posts log strings, the GUI polls every 100 ms via `after()`.

```
┌─────────────────────────────────────────────────────────┐
│  main.py  (entry point — adds src/ to sys.path)         │
│     └── OmniConvertApp  (CustomTkinter, main thread)    │
│           │                                             │
│           │  spawns daemon thread on Convert click      │
│           ▼                                             │
│  converters/pipeline.py  (background thread)            │
│     ├── to_markdown.py   (input parsers)                │
│     ├── from_markdown.py (output generators)            │
│     ├── hifi.py          (layout-preserving path)       │
│     └── assets.py        (cover extraction)             │
└─────────────────────────────────────────────────────────┘
```

---

## Conversion Architecture: Hub-and-Spoke

Every format is first reduced to Markdown (the hub), then compiled to the target format from that Markdown source. This keeps the conversion matrix linear — N parsers + N generators instead of N² direct converters.

```
  .pdf   ─┐                                   ┌─► .pdf  (weasyprint)
  .docx  ─┤──► to_markdown ──► [ .md + imgs ] ─┤──► .docx (pandoc)
  .epub  ─┤                                   ├──► .epub (pandoc)
  .txt   ─┘                                   ├──► .txt  (pandoc)
  .md    ──────────────────────────────────── └──► .md   (copy)
```

Intermediate `.md` files and image folders are written to the **same directory as the source file** and kept after conversion. This makes outputs natively compatible with AI pipelines and local LLM tooling.

---

## Conversion Modes

### Standard (default)

Full hub-and-spoke pipeline. Works for all 20 format pairs.

| Step | Action |
|------|--------|
| 1 | Parse source → `{stem}_{ext}.md` + `{stem}_{ext}_img/` |
| 2 | Extract cover → `{stem}_{ext}_cover.png` |
| 3 | Compile `.md` → target format (final output `{stem}.{target}`, auto-suffixed `(1)`, `(2)` on collision) |

Intermediate filenames suffix the source extension (`Draft.pdf` → `Draft_pdf.md`) so `Draft.pdf` and `Draft.docx` in the same folder never overwrite each other.

### High-Fidelity (PDF ↔ DOCX)

Bypasses the Markdown hub entirely. Two paths:

**PDF → DOCX via `pdf2docx`** — preserves columns, float positions, table borders, fonts.
| Step | Action |
|------|--------|
| 1 | `pdf2docx.Converter.convert()` → `.docx` |
| 2 | `cv.close()` releases file handle |
| 3 | Cover extracted via PyMuPDF (after close) |

**Critical ordering:** Cover extraction always happens after `cv.close()`. Both tools open the same PDF file; interleaving them causes a file-lock conflict on Windows.

**DOCX → PDF via `docx2pdf` (Microsoft Word COM)** — preserves page margins, headers, footers, page numbers, fonts. Requires Word installed.
| Step | Action |
|------|--------|
| 1 | `pythoncom.CoInitialize()` — required because the pipeline runs on a daemon thread, not main |
| 2 | `docx2pdf.convert()` — drives Word in the background |
| 3 | `pythoncom.CoUninitialize()` — prevents `WINWORD.EXE` zombie leaks |

If `docx2pdf` raises (Word missing / COM error), the pipeline catches the exception and falls back to the Standard `DOCX → MD → HTML → PDF` path with a log warning.

---

## Batch Processing

The pipeline runs files **sequentially on a single daemon thread** — no parallelism. This is a deliberate accuracy-over-speed choice:
- PyMuPDF and pdf2docx both open the same PDF file at different stages; parallel batches would race on file locks.
- MS Word via COM is single-instance per thread.
- Memory stays bounded — `gc.collect()` runs between each file to free PyMuPDF's C-allocated buffers.

```
GUI (main thread)
  └── pipeline.start_batch(sources, fmt, mode, extract_cover, log_q)
        └── threading.Thread(daemon=True) ─► run_batch()
                                                ├── for each source:
                                                │     ├── __FILE_START__N
                                                │     ├── _run_single() ──► converters/*
                                                │     ├── __FILE_DONE__N (or __FILE_ERROR__N)
                                                │     └── gc.collect()
                                                └── __BATCH_DONE__
```

**Continue-on-error policy:** one bad file logs `[✗] {name}: {error}`, marks the row `✗`, and the batch proceeds. Final summary line: `[✓] Batch complete: N succeeded, M failed`.

**Single-file path is preserved** — internally `run()` just calls `_run_single()` and posts `__DONE__` instead of the batch markers. Backward-compatible with any code that used the v0.1.0 entry points.

---

## Memory management

PyMuPDF (`fitz`) allocates document buffers in C; Python's GC doesn't reclaim them as aggressively as native Python objects. A 100-PDF batch left to its own devices will balloon to gigabytes of RSS.

Mitigations baked into the pipeline:
- `assets.py::_cover_pdf` explicitly calls `doc.close()` on every PDF it opens
- `hifi.py::pdf_to_docx` calls `cv.close()` in a `finally` block
- `pipeline.py::_run_single` calls `gc.collect()` in its `finally` block — runs once per file in batch mode

**Do not strip the `gc.collect()` call** thinking it's superstition. Without it, large batches OOM.

---

## Library Responsibilities

### Input Parsers (`to_markdown.py`)

| Format | Library | Notes |
|--------|---------|-------|
| PDF | `pymupdf4llm` | Column-aware, footnote-aware; `write_images=True` extracts all embedded images |
| DOCX | `markitdown` | Microsoft's MarkItDown; handles tables and inline images |
| EPUB | `ebooklib` + `html2text` | Iterates OPF spine in order; saves embedded images to `_img/` |
| TXT | built-in | Passthrough copy |
| MD | built-in | Passthrough copy |

### Output Generators (`from_markdown.py`)

| Format | Engine | Notes |
|--------|--------|-------|
| PDF | `weasyprint` (PRIMARY) | MD → HTML via `markdown` lib → PDF; `base_url` resolves image paths |
| DOCX | `pypandoc` → pandoc | `--resource-path` points to `_img/` folder |
| EPUB | `pypandoc` → pandoc | `--epub-cover-image` attaches extracted cover |
| TXT | `pypandoc` → pandoc | `plain` format |
| MD | built-in | Copy of hub file |

### Cover Extraction (`assets.py`)

| Format | Strategy |
|--------|----------|
| PDF | Render page 0 at 2× scale via PyMuPDF; use largest embedded image if its area exceeds 25% of the page render |
| DOCX | Unzip `.docx`, find largest file > 5 KB in `word/media/` |
| EPUB | `ebooklib` manifest — find `cover-image` item by id, then by `ITEM_COVER` type, then first image |

---

## Dependency Map

```
OmniConvert
├── customtkinter          GUI framework
├── Pillow                 Image resizing for cover preview
├── pymupdf4llm            PDF → Markdown (pulls pymupdf)
│   └── pymupdf            Also used directly in assets.py
├── markitdown[docx]       DOCX → Markdown
├── ebooklib               EPUB parse
├── html2text              EPUB XHTML → Markdown
├── markdown               MD → HTML (weasyprint path)
├── weasyprint             HTML → PDF
├── pypandoc               Python wrapper for pandoc CLI
│   └── pandoc             System binary (vendor/pandoc/pandoc.exe)
└── pdf2docx               High-Fidelity PDF → DOCX
```

---

## File Naming Convention

All outputs land in the same directory as the source file. Colons are replaced with hyphens; runs of whitespace are collapsed.

```
Source:   C:\Books\My Book - 2024: Final.pdf
Stem:     My Book - 2024- Final          (sanitize_stem)

Hub MD:   My Book - 2024- Final.md
Images:   My Book - 2024- Final_img\
Cover:    My Book - 2024- Final_cover.png
Output:   My Book - 2024- Final.docx
```

---

## Threading Model

```
Main thread (CustomTkinter event loop)
│
│  Convert button click
│    └── threading.Thread(target=pipeline.run, daemon=True).start()
│
│  after(100ms, _poll_log)  ◄─── repeats while _converting == True
│    └── queue.Queue.get_nowait()
│          ├── log string  →  append to CTkTextbox
│          ├── __DONE__{path}  →  re-enable button, load cover preview
│          └── __ERROR__       →  re-enable button
```

The Convert button callback **never** calls `pipeline.run()` directly — doing so would block the Tk event loop for the full duration of conversion.

---

## Windows Path Safety

`converters/pipeline.py::sanitize_stem()` handles Windows edge cases:

```python
name = name.replace(":", "-")           # colons invalid in filenames
name = re.sub(r"\s+", " ", name).strip()  # collapse whitespace
name = name.strip(". ")                 # no leading/trailing dots or spaces
# Prefix reserved names: CON, PRN, AUX, NUL, COM1-9, LPT1-9
```

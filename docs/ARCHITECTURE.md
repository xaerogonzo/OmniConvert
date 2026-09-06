# Architecture

## Overview

OmniConvert is a single-process Python desktop application. The GUI runs on the main thread; all conversion work runs on a daemon background thread. A `queue.Queue` bridges the two — the pipeline posts log strings, the GUI polls every 100 ms via `after()`.

```
┌─────────────────────────────────────────────────────────┐
│  main.py  (entry point — adds src/ to sys.path)         │
│     └── OmniConvertApp  (CustomTkinter, main thread)    │
│           ├── ui/queue_model.py   (Tk-free queue state) │
│           ├── ui/queue_panel.py   (cover + queue rows)  │
│           ├── ui/controls_panel.py(format/mode/progress)│
│           └── ui/log_panel.py     (log textbox)         │
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
  .pdf   ─┐                                   ┌─► .pdf  (pymupdf)   
  .docx  ─┤──► to_markdown ──► [ .md + imgs ] ─┤──► .docx (pandoc)
  .epub  ─┤                                   ├──► .epub (pandoc)
  .txt   ─┘                                   ├──► .txt  (pandoc)
  .md    ──────────────────────────────────── └──► .md   (copy)
```

Intermediate `.md` files and image folders are written to the **effective output root** and kept after conversion, which makes them natively compatible with AI pipelines and local LLM tooling.

The output root is `ConvertParams.dest_dir`, defaulting to the source file's own
directory. It is a *root*, not a destination for the final file alone: the
output, the hub `.md`, the `_img/` folder and the cover all live under it
together. Splitting them would break the image-reference contract below. Set
`keep_intermediates=False` to delete the hub and image folder after a successful
conversion (the cover is always kept - the queue panel previews it).

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
| DOCX | `mammoth` + `markitdown` | mammoth → HTML with our own image handler (real files in `_img/`), then markitdown for HTML → Markdown so table/heading fidelity is kept. markitdown's OMML pre-pass still turns Word equations into LaTeX. |
| EPUB | `ebooklib` + `html2text` | Iterates OPF spine in order; saves embedded images to `_img/` |
| TXT | built-in | Passthrough copy |
| MD | built-in | Passthrough copy |

### Output Generators (`from_markdown.py`)

| Format | Engine | Notes |
|--------|--------|-------|
| PDF | `pymupdf` Story (PRIMARY) | MD → HTML via `markdown` lib → PDF; `archive` resolves image paths |
| DOCX | `pypandoc` → pandoc | `--resource-path` points to the `.md`'s parent |
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
├── markdown               MD → HTML (PDF path)
├── mammoth                DOCX → HTML with file-backed images
├── pypandoc               Python wrapper for pandoc CLI
│   └── pandoc             System binary (vendor/pandoc/pandoc.exe)
└── pdf2docx               High-Fidelity PDF → DOCX
```

---

## File Naming Convention

All outputs land in the effective output root - by default the source file's own directory. Colons are replaced with hyphens; runs of whitespace are collapsed.

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

---

## Image Reference Contract

Every parser writes image references that **already include the image folder
name** — `![](Draft_pdf_img/x.png)`, not `![](x.png)`. Every output generator
must therefore resolve them against the directory **containing the `.md`**, never
against the image folder itself:

| Generator | Setting | Value |
|---|---|---|
| PDF (`pymupdf` Story) | `archive=` | `md_path.parent` |
| DOCX / EPUB / TXT (pandoc) | `--resource-path=` | `md_path.parent` |

Pointing either at `img_dir` makes the reference resolve one level too deep
(`img_dir/img_dir/x.png`). WeasyPrint surfaced this as visibly broken images in
v0.2.0 and it was fixed there; pandoc failed the same way but only emitted a
`Could not fetch resource` warning to stderr, so EPUB and DOCX output silently
shipped without images until v0.3.0. **If you add an output generator, this table
is the rule to follow.**

Stems can contain spaces, so DOCX references are percent-encoded
(`Smoke%20Doc_docx_img/img_001.png`). A raw space would terminate the URL early
in Markdown and break the reference.

### Two consequences of a configurable output root

**The artifact set must resolve to one stem.** `{stem}.md`, `{stem}_img/` and
`{stem}_cover.png` are derived from a single `_claim_base_stem()` result.
Resolving each independently yields `Book_pdf (1).md` beside `Book_pdf_img (1)`,
so the markdown points at `Book_pdf (1)_img/`, which does not exist. Collisions
are only broken *within a run* (via the `claimed` set), so re-converting a file
still overwrites its own artifacts rather than accumulating `(1)`, `(2)`, ...

**Passthrough sources keep their images where they were.** Converting a `.md`
into a different output root moves the hub but not the images beside the
original file. Generators therefore resolve against *several* roots - the
markdown's parent first, then the source's - via `from_markdown._asset_roots()`,
using `pymupdf.Archive` for PDF and an `os.pathsep`-joined `--resource-path` for
pandoc.

---

## Why PyMuPDF and not WeasyPrint

WeasyPrint needs the GTK/Pango shared libraries at import time. On Windows those
are a separate several-hundred-megabyte system install (MSYS2 `pacman -S
mingw-w64-x86_64-pango`, or `WEASYPRINT_DLL_DIRECTORIES` pointing at them).
Nuitka cannot bundle libraries that are not present, so an `OmniConvert.exe`
built against WeasyPrint could not produce a PDF on any machine lacking GTK — and
on such a machine `from weasyprint import HTML` raises `OSError` before any
conversion starts.

PyMuPDF is already a hard dependency (via `pymupdf4llm`), needs no system
libraries, and bundles cleanly. Its `Story` renderer supports a CSS subset.
Verified as honoured: font families, table borders and header fills, embedded
images, code blocks. Verified as *not* honoured: `max-width` / `margin: auto`
(the text column is set by the placement rectangle in `_to_pdf` instead) and
`page-break-after`.

---

## Cancellation

`run_batch` accepts an optional `threading.Event` and checks it **between files
only**, then posts `__BATCH_CANCELLED__` instead of `__BATCH_DONE__`.

This is deliberate. Aborting a file mid-conversion would abandon a thread holding
PyMuPDF's C-allocated buffers or a live MS Word COM instance — precisely what the
`cv.close()`, `gc.collect()` and `CoUninitialize()` rules above exist to prevent.
A long PDF already inside `pdf2docx` therefore finishes before the batch stops,
and the GUI says so (`Cancel requested — finishing the current file first…`).

---

## Nuitka Build Configuration

The build (`build.ps1`, launched by `build.bat`) compiles a one-file
`dist\OmniConvert.exe`. Three rules keep it working:

**1. Do not exclude what the app actually imports.** The exclusion block began as
generic "Anaconda bloat" filtering and was wrong for this project:

| Package | Reached via | Status |
|---|---|---|
| `numpy` | `pdf2docx` -> `cv2` | **must be bundled** |
| `pandas` | `markitdown`, *only if pandas is installed* | **not excluded** |
| `cv2` | `pdf2docx` | **must be bundled** |
| `sympy` | `pdf2docx` -> `fontTools` -> `fontTools.misc.symfont` | excluded - unused |
| `scipy`, `matplotlib`, `sklearn`, `IPython`, `notebook` | not reached | excluded |

Excluding `numpy` produced an `.exe` that raised `ImportError` on **every DOCX
source** and on **High-Fidelity PDF -> DOCX**.

`pandas` is a subtler case and the entry above is deliberately conditional.
markitdown does *not* require it - in a clean virtualenv markitdown imports only
numpy. But markitdown has optional converters that import pandas *when it happens
to be installed*, so a build run from an environment that has pandas (a shared
conda base, say) will trace into it. Excluding it would then break DOCX in the
exe while working perfectly from source. Leaving it un-excluded costs nothing
when pandas is absent and is correct when it is present - which is also why the
build should be run from the project venv, where the dependency set is exactly
the pinned one. That shipped from
v0.2.0 and went unnoticed because the build never survived long enough to emit a
binary. `tests/test_build_script.py` now asserts the include and exclude sets do
not contradict each other.

Excluding `sympy` matters in the other direction: without it Nuitka compiles all
~1000 sympy modules for the sake of one unused symbolic-font-math helper - 5958
object files, 3.2 GB, and a build that stalls before linking.

**2. `build.ps1` must stay pure ASCII.** `build.bat` invokes Windows PowerShell
5.1, which reads BOM-less files as cp1252. A UTF-8 em-dash decodes to three
characters ending in U+201D, which PowerShell accepts as a string delimiter - so
the enclosing string closes early and the script fails to parse. This silently
broke `.\build.bat` until v0.3.0.

**3. `build.bat` must propagate the exit code.** It previously ended with `pause`
and returned 0 unconditionally, so a script that failed to parse still looked
like a successful build.

**Drag-and-drop depends on a data-dir flag**, not just a package inclusion:
`--include-data-dir=<tkinterdnd2>/tkdnd=tkinterdnd2/tkdnd`. Without it DnD breaks
only in the frozen exe, never when running from source - so always test a drop on
the built binary.

"""OmniConvert — offline document converter with CustomTkinter GUI.

v0.3: the window is now a thin shell. Queue state lives in a Tk-free
`ui.QueueModel`, and the three regions of the window are separate panels under
`omniconvert.ui`. This module owns only the root window, the OS drop bindings,
the pipeline handoff, and the log-marker dispatch.

Threading contract (unchanged, and load-bearing):
  * Convert only ever spawns `threading.Thread(daemon=True)` via `pipeline`.
  * The worker posts strings to a `queue.Queue`; it never touches a widget.
  * `_poll_log` runs on the main thread via `after()` and is the only place
    widgets are updated in response to worker progress.
"""

from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

from omniconvert.converters import pipeline
from omniconvert.converters.pipeline import _intermediate_paths
from omniconvert.ui import ControlsPanel, LogPanel, QueueModel, QueuePanel
from omniconvert.ui.constants import PANDOC_TARGETS, SUPPORTED

# ---------------------------------------------------------------------------
# Vendor pandoc auto-detection (portable install via scripts/install_pandoc.py)
# ---------------------------------------------------------------------------

# __file__ is src/omniconvert/app.py — go up to project root
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_VENDOR_PANDOC = _PROJECT_ROOT / "vendor" / "pandoc"
if _VENDOR_PANDOC.exists() and str(_VENDOR_PANDOC) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(_VENDOR_PANDOC) + ";" + os.environ.get("PATH", "")

PANDOC_AVAILABLE = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _check_pandoc() -> bool:
    try:
        import pypandoc

        pypandoc.get_pandoc_version()
        return True
    except Exception:
        return False


def cover_path_for(src: Path) -> Path:
    """Where the pipeline will have written this source's cover.

    Delegates to pipeline._intermediate_paths so the naming convention lives in
    exactly one place — it used to be re-derived by hand in two methods here.
    """
    return _intermediate_paths(src)[4]


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class OmniConvertApp(ctk.CTk, TkinterDnD.DnDWrapper):
    """OmniConvert main window.

    Mixes CustomTkinter's CTk root with TkinterDnD's DnDWrapper so the window
    can register as an OS-level file-drop target.
    """

    def __init__(self) -> None:
        super().__init__()
        # Bootstrap TkinterDnD on the existing Tk instance. This loads the
        # tkdnd2.x TCL extension and enables drop_target_register / dnd_bind.
        # MUST run before any drop_target_register call below.
        self.TkdndVersion = TkinterDnD._require(self)

        self.title("OmniConvert")
        self.geometry("960x720")
        self.resizable(False, False)

        # ---- State ----
        self.model = QueueModel()
        self._log_q: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._converting = False

        self._build_ui()
        self._update_convert_button()

    # ==================================================================
    # UI construction
    # ==================================================================

    def _build_ui(self) -> None:
        self.grid_rowconfigure(0, weight=0)  # pandoc banner
        self.grid_rowconfigure(1, weight=0)  # drop zone
        self.grid_rowconfigure(2, weight=1)  # main content
        self.grid_rowconfigure(3, weight=0)  # log
        self.grid_columnconfigure(0, weight=1)

        self._build_pandoc_banner()
        self._build_drop_zone()

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=2, column=0, sticky="nsew", padx=20, pady=14)
        main.grid_columnconfigure(0, weight=0)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        self.queue_panel = QueuePanel(
            main, self.model,
            on_row_click=self._on_queue_row_click,
            on_cover_click=self._open_cover,
        )
        self.queue_panel.grid(row=0, column=0, sticky="ns", padx=(0, 14))

        self.controls = ControlsPanel(
            main,
            on_format_change=self._on_format_change,
            on_mode_change=self._on_mode_change,
            on_convert=self._on_convert_or_cancel,
        )
        self.controls.grid(row=0, column=1, sticky="nsew")

        self.log_panel = LogPanel(self)
        self.log_panel.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 14))

        # Register the entire window as a drop target
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>",      self._on_drop)
        self.dnd_bind("<<DropEnter>>", self._on_drop_enter)
        self.dnd_bind("<<DropLeave>>", self._on_drop_leave)

    def _build_pandoc_banner(self) -> None:
        global PANDOC_AVAILABLE
        PANDOC_AVAILABLE = _check_pandoc()

        self._banner = ctk.CTkFrame(self, fg_color="#7a5c00", corner_radius=0)
        ctk.CTkLabel(
            self._banner,
            text="⚠  Pandoc not found — DOCX / EPUB / TXT output disabled.  "
                 "Run scripts/install_pandoc.py then restart.",
            text_color="#ffe066",
            font=ctk.CTkFont(size=12),
        ).pack(pady=6, padx=12)

        if not PANDOC_AVAILABLE:
            self._banner.grid(row=0, column=0, sticky="ew")

    def _build_drop_zone(self) -> None:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(14, 0))
        frame.grid_columnconfigure(4, weight=1)

        ctk.CTkButton(frame, text="Browse Files…", width=120,
                      command=self._on_browse_files).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(frame, text="Add Folder…", width=110,
                      command=self._on_add_folder).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(frame, text="Clear", width=70, fg_color="#3a3a3a",
                      hover_color="#4a4a4a",
                      command=self._on_clear).grid(row=0, column=2, padx=(0, 8))
        ctk.CTkButton(frame, text="Open Folder", width=110, fg_color="#3a3a3a",
                      hover_color="#4a4a4a",
                      command=self._open_output_folder).grid(row=0, column=3,
                                                             padx=(0, 12))

        self._file_label = ctk.CTkLabel(
            frame,
            text="No files queued  —  drop PDFs, DOCXs, EPUBs, MDs, TXTs here  "
                 "(or a folder)",
            anchor="w", text_color="gray", font=ctk.CTkFont(size=12),
        )
        self._file_label.grid(row=0, column=4, sticky="ew")

    # ==================================================================
    # Input handlers — all guard against mid-batch mutation
    # ==================================================================

    def _reject_if_converting(self, what: str) -> bool:
        if self._converting:
            self._log(f"[!] Batch in progress — {what} rejected. "
                      f"Wait for completion.")
            return True
        return False

    def _on_drop(self, event):
        """Handle file/folder drop events from tkinterdnd2."""
        self._on_drop_leave(event)  # restore label colour/text first
        if self._reject_if_converting("drop"):
            return
        paths = [Path(p) for p in self.tk.splitlist(event.data)]
        expanded: list[Path] = []
        for p in paths:
            if p.is_dir():
                expanded.extend(self._scan_folder(p))
            elif p.is_file() and p.suffix.lower() in SUPPORTED:
                expanded.append(p)
        if not expanded:
            self._log("[!] No supported files in drop")
            return
        self._enqueue(expanded)

    def _on_drop_enter(self, event):
        self._file_label.configure(text="Drop to load…", text_color="#4a9eff")
        return event.action

    def _on_drop_leave(self, event):
        self._refresh_file_label()
        return event.action

    def _on_browse_files(self):
        if self._reject_if_converting("browse"):
            return
        paths = filedialog.askopenfilenames(
            title="Select documents",
            filetypes=[
                ("Supported documents", "*.pdf *.docx *.epub *.md *.txt"),
                ("PDF", "*.pdf"),
                ("Word Document", "*.docx"),
                ("EPUB", "*.epub"),
                ("Markdown", "*.md"),
                ("Plain Text", "*.txt"),
            ],
        )
        valid = [Path(p) for p in paths if Path(p).suffix.lower() in SUPPORTED]
        if valid:
            self._enqueue(valid)

    def _on_add_folder(self):
        if self._reject_if_converting("folder add"):
            return
        folder = filedialog.askdirectory(title="Select a folder to scan")
        if not folder:
            return
        files = self._scan_folder(Path(folder))
        if not files:
            self._log(f"[!] No supported files in {folder}")
            return
        self._enqueue(files)

    def _on_clear(self):
        if self._reject_if_converting("clear"):
            return
        self.model.clear()
        self._refresh_queue_ui()
        self.controls.set_source("—")
        self.queue_panel.set_cover(None)
        self._log("[*] Queue cleared")

    def _scan_folder(self, folder: Path) -> list[Path]:
        recursive = self.controls.include_subfolders
        try:
            iterator = folder.rglob("*") if recursive else folder.iterdir()
            return sorted(
                p for p in iterator
                if p.is_file() and p.suffix.lower() in SUPPORTED
            )
        except (OSError, PermissionError) as exc:
            self._log(f"[!] Folder scan failed: {exc}")
            return []

    # ==================================================================
    # Queue state
    # ==================================================================

    def _enqueue(self, paths: list[Path]) -> None:
        """Append to the queue (v0.2 replaced it wholesale; now it accumulates)."""
        was_empty = not self.model
        added = self.model.add(paths)
        skipped = len(paths) - added

        self._refresh_queue_ui()

        if added:
            msg = f"[*] Queued {added} file(s)"
            if skipped:
                msg += f" ({skipped} already in queue)"
            self._log(msg)
        else:
            self._log(f"[!] All {skipped} file(s) already queued")

        if was_empty and self.model:
            self.controls.set_source(self.model[0].path.name)
            self._preview_cover_for_row(0)

    def _refresh_queue_ui(self) -> None:
        self.queue_panel.rebuild()
        self._refresh_file_label()
        self._on_format_change(self.controls.fmt_var.get())
        self._update_convert_button()

    def _refresh_file_label(self) -> None:
        n = len(self.model)
        if n == 0:
            self._file_label.configure(
                text="No files queued  —  drop PDFs, DOCXs, EPUBs, MDs, TXTs "
                     "here  (or a folder)",
                text_color="gray",
            )
        elif n == 1:
            p = self.model[0].path
            try:
                size = f"  ({p.stat().st_size / (1024 * 1024):.1f} MB)"
            except OSError:
                size = ""
            self._file_label.configure(text=f"{p.name}{size}", text_color="white")
        else:
            self._file_label.configure(text=f"{n} files queued", text_color="white")

    def _on_queue_row_click(self, idx: int) -> None:
        self.model.select(idx, converting=self._converting)
        self.queue_panel.render_status()
        self._preview_cover_for_row(idx)

    def _preview_cover_for_row(self, idx: int) -> None:
        if not 0 <= idx < len(self.model):
            self.queue_panel.set_cover(None)
            return
        self.queue_panel.set_cover(cover_path_for(self.model[idx].path))

    # ==================================================================
    # Format / mode controls
    # ==================================================================

    def _on_format_change(self, value: str) -> None:
        """High-Fidelity is only meaningful for the PDF/DOCX pairs."""
        fmt = value.lower()
        src_ext = self.model[0].path.suffix.lower() if self.model else ""
        hifi_valid = (
            (src_ext == ".pdf" and fmt == "docx")
            or (src_ext == ".docx" and fmt == "pdf")
        )
        self.controls.set_hifi_enabled(hifi_valid)
        self._update_convert_button()

    def _on_mode_change(self, value: str) -> None:
        self._update_convert_button()

    # ==================================================================
    # Convert / cancel
    # ==================================================================

    def _on_convert_or_cancel(self) -> None:
        if self._converting:
            self._cancel.set()
            self.controls.set_convert_button(
                text="Cancelling…", enabled=False, danger=True
            )
            self._log("[!] Cancel requested — finishing the current file first…")
            return

        if not self.model:
            return

        self._converting = True
        self._cancel.clear()
        self.model.reset_statuses()
        self.queue_panel.render_status()
        self.controls.set_progress(0)
        self.controls.set_inputs_enabled(False)
        self.controls.set_hifi_enabled(False)
        self.controls.set_convert_button(text="Cancel", enabled=True, danger=True)

        pipeline.start_batch(
            sources=self.model.paths,
            target_fmt=self.controls.fmt_var.get().lower(),
            mode=("hifi" if self.controls.mode_var.get() == "High-Fidelity"
                  else "standard"),
            extract_cover=self.controls.extract_cover,
            strict_tables=self.controls.strict_tables,
            cancel=self._cancel,
            log_q=self._log_q,
        )
        self.after(100, self._poll_log)

    def _update_convert_button(self) -> None:
        """Update label and enabled state. Call after queue/format/mode changes."""
        if self._converting:
            return

        fmt = self.controls.fmt_var.get().lower()
        needs_pandoc = fmt in PANDOC_TARGETS
        mode_is_hifi = self.controls.mode_var.get() == "High-Fidelity"

        n = len(self.model)
        label = f"Convert Batch ({n})" if n > 1 else "Convert"
        enabled = n > 0 and (PANDOC_AVAILABLE or not needs_pandoc or mode_is_hifi)
        self.controls.set_convert_button(text=label, enabled=enabled)

    def _finish_conversion(self) -> None:
        """Common teardown when a batch finishes (success, error or cancel)."""
        self._converting = False
        self._cancel.clear()
        self.model.running_idx = -1
        self.controls.set_inputs_enabled(True)
        self.controls.set_progress(0)
        # Mode availability depends on the current source/target pair
        self._on_format_change(self.controls.fmt_var.get())
        self._update_convert_button()

    # ==================================================================
    # Log polling — drains the queue and dispatches markers
    # ==================================================================

    def _poll_log(self) -> None:
        try:
            while True:
                msg = self._log_q.get_nowait()

                if msg.startswith("__FILE_START__"):
                    n = int(msg[len("__FILE_START__"):])
                    self.model.set_running(n)
                    self.queue_panel.render_status()
                    self.controls.set_progress(n / (len(self.model) or 1))
                    # Auto-track the preview unless the user pinned a row
                    if self.model.is_auto_tracking:
                        self._preview_cover_for_row(n)
                        self.controls.set_source(self.model[n].path.name)

                elif msg.startswith("__FILE_DONE__"):
                    n = int(msg[len("__FILE_DONE__"):])
                    self.model.set_status(n, "done")
                    self.queue_panel.render_status()
                    self.controls.set_progress((n + 1) / (len(self.model) or 1))
                    # The cover may only just have appeared on disk
                    if self.model.is_auto_tracking and self.model.running_idx == n:
                        self._preview_cover_for_row(n)

                elif msg.startswith("__FILE_ERROR__"):
                    n = int(msg[len("__FILE_ERROR__"):])
                    self.model.set_status(n, "error")
                    self.queue_panel.render_status()
                    self.controls.set_progress((n + 1) / (len(self.model) or 1))

                elif msg in ("__BATCH_DONE__", "__BATCH_CANCELLED__", "__ERROR__"):
                    self._finish_conversion()
                    return

                elif msg.startswith("__DONE__"):
                    # Legacy single-file marker, kept for backward compatibility
                    self._finish_conversion()
                    return

                else:
                    self._log(msg)
        except queue.Empty:
            pass

        if self._converting:
            self.after(100, self._poll_log)

    def _log(self, text: str) -> None:
        self.log_panel.log(text)

    # ==================================================================
    # Shell integration
    # ==================================================================

    def _open_cover(self) -> None:
        """Open the currently-previewed cover in the system default viewer."""
        idx = self.model.preview_idx
        if not 0 <= idx < len(self.model):
            return
        cover = cover_path_for(self.model[idx].path)
        if cover.exists():
            self._reveal(cover)
        else:
            self._log("[!] No cover extracted for this file yet")

    def _open_output_folder(self) -> None:
        """Open the folder outputs are written to (alongside the source file)."""
        idx = max(self.model.preview_idx, 0)
        if not 0 <= idx < len(self.model):
            self._log("[!] Nothing queued — no output folder to open")
            return
        self._reveal(self.model[idx].path.parent)

    def _reveal(self, target: Path) -> None:
        try:
            os.startfile(str(target))
        except (OSError, AttributeError) as exc:
            self._log(f"[!] Could not open {target.name}: {exc}")

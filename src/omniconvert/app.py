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
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

from omniconvert import settings
from omniconvert.converters import markers, pipeline
from omniconvert.converters.pipeline import _intermediate_paths
from omniconvert.ui import (
    ControlsPanel,
    LogPanel,
    QueueModel,
    QueuePanel,
    ToolbarPanel,
)
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

_DEFAULT_GEOMETRY = "960x720"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _check_pandoc() -> bool:
    try:
        import pypandoc

        pypandoc.get_pandoc_version()
        return True
    except Exception:
        return False


def cover_path_for(src: Path, dest_dir: Path | None = None) -> Path:
    """Where the pipeline will have written this source's cover.

    Delegates to pipeline._intermediate_paths so the naming convention lives in
    exactly one place — it used to be re-derived by hand in two methods here.
    `dest_dir` must match what the conversion used, or the preview quietly looks
    in the wrong folder and reports "No cover".
    """
    return _intermediate_paths(src, dest_dir)[4]


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
        self._settings = settings.load()
        self._apply_geometry(self._settings.geometry)
        self.resizable(False, False)

        # ---- State ----
        self.model = QueueModel()
        self._log_q: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._converting = False
        self._dest_dir: Path | None = None   # None = beside the source
        # A run operates on an immutable snapshot of the queue. Worker
        # markers index the SUBMITTED list - the whole queue for a full run,
        # only the failed rows for a retry - so the mapping back to model
        # rows is recorded at submission time and used for the whole run.
        self._batch_sources: list[Path] = []
        self._batch_indices: list[int] = []

        self._build_ui()
        # Before _update_convert_button, so a restored format that needs an
        # absent pandoc still ends up with the button disabled.
        self._apply_settings()
        self._update_convert_button()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================================================================
    # Preferences
    # ==================================================================

    def _apply_geometry(self, saved: str | None) -> None:
        """Restore the window size/position, tolerating anything odd.

        CustomTkinter parses the geometry string itself for DPI scaling, so a
        malformed one surfaces as TypeError from *its* code rather than the
        tk.TclError you would expect. `settings` validates the string too; this
        is the second line of defence, because failing here happens during
        __init__ and would stop the app from starting at all.
        """
        for candidate in (saved, _DEFAULT_GEOMETRY):
            if not candidate:
                continue
            try:
                self.geometry(candidate)
                return
            except (tk.TclError, TypeError, ValueError):
                continue

    def _apply_settings(self) -> None:
        s = self._settings
        self.controls.fmt_var.set(s.target_fmt)
        self.controls.set_preferred_mode(s.mode)
        self.controls.set_options(
            extract_cover=s.extract_cover,
            strict_tables=s.strict_tables,
            include_subfolders=s.include_subfolders,
            keep_intermediates=s.keep_intermediates,
        )
        # A saved folder can be gone by now; the resolver decides, not us.
        self._dest_dir = s.effective_dest_dir()
        self._refresh_dest_label()
        self._on_format_change(self.controls.fmt_var.get())

    def _current_settings(self) -> settings.Settings:
        return settings.Settings(
            target_fmt=self.controls.fmt_var.get(),
            mode=self.controls.preferred_mode,
            extract_cover=self.controls.extract_cover,
            strict_tables=self.controls.strict_tables,
            include_subfolders=self.controls.include_subfolders,
            keep_intermediates=self.controls.keep_intermediates,
            dest_dir=self._dest_dir,
            geometry=self.winfo_geometry(),
        )

    def _on_close(self) -> None:
        # Preferences only - never the queue, statuses or the last error.
        settings.save(self._current_settings())
        self.destroy()

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
        self._build_toolbar()

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=2, column=0, sticky="nsew", padx=20, pady=14)
        main.grid_columnconfigure(0, weight=0)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        self.queue_panel = QueuePanel(
            main, self.model,
            on_row_click=self._on_queue_row_click,
            on_row_remove=self._on_row_remove,
            on_cover_click=self._open_cover,
        )
        self.queue_panel.grid(row=0, column=0, sticky="ns", padx=(0, 14))

        self.controls = ControlsPanel(
            main,
            on_format_change=self._on_format_change,
            on_mode_change=self._on_mode_change,
            on_convert=self._on_convert_or_cancel,
            on_retry=self._on_retry_failed,
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

    def _build_toolbar(self) -> None:
        self.toolbar = ToolbarPanel(
            self,
            on_browse=self._on_browse_files,
            on_add_folder=self._on_add_folder,
            on_clear=self._on_clear,
            on_open_folder=self._open_output_folder,
            on_choose_output=self._on_choose_output,
            on_reset_output=self._on_clear_output,
        )
        self.toolbar.grid(row=1, column=0, sticky="ew", padx=20, pady=(14, 0))

    # ==================================================================
    # Output destination — one resolver, every consumer derives from it
    # ==================================================================

    def _effective_dest_dir(self) -> Path | None:
        """The destination actually usable right now.

        A chosen folder can disappear between selection and use (removable
        drive, network share, or simply deleted), so this is the only place that
        decides — cover preview, open-cover, open-folder and the conversion all
        ask here rather than each holding their own interpretation.
        """
        if self._dest_dir is not None and self._dest_dir.is_dir():
            return self._dest_dir
        return None

    def _on_choose_output(self) -> None:
        if self._reject_if_converting("output folder change"):
            return
        chosen = filedialog.askdirectory(title="Choose an output folder")
        if not chosen:
            return
        self._dest_dir = Path(chosen)
        self._refresh_dest_label()
        self._log(f"[*] Output folder: {self._dest_dir}")
        # Covers for already-queued files now resolve somewhere else.
        self._preview_cover_for_row(self.model.preview_idx)

    def _on_clear_output(self) -> None:
        if self._reject_if_converting("output folder change"):
            return
        self._dest_dir = None
        self._refresh_dest_label()
        self._log("[*] Output folder: beside each source file")
        self._preview_cover_for_row(self.model.preview_idx)

    def _refresh_dest_label(self) -> None:
        self.toolbar.set_output_destination(self._dest_dir)

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
        self.toolbar.show_drop_hint()
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
        self.controls.set_retry_enabled(
            self.model.has_failures and not self._converting
        )

    def _refresh_file_label(self) -> None:
        self.toolbar.set_queue_summary(self.model.paths)

    def _on_row_remove(self, idx: int) -> None:
        """Drop one row from the queue.

        Refused mid-batch: worker markers index the submitted list, so removing
        a row would shift every later index and mark the wrong files done.
        """
        if self._reject_if_converting("row removal"):
            return
        if not 0 <= idx < len(self.model):
            return
        name = self.model[idx].path.name
        self.model.remove(idx)
        self._refresh_queue_ui()
        self._log(f"[*] Removed {name}")
        if not self.model:
            self.controls.set_source("—")
            self.queue_panel.set_cover(None)

    def _on_queue_row_click(self, idx: int) -> None:
        self.model.select(idx, converting=self._converting)
        self.queue_panel.render_status()
        self._preview_cover_for_row(idx)

    def _preview_cover_for_row(self, idx: int) -> None:
        if not 0 <= idx < len(self.model):
            self.queue_panel.set_cover(None)
            return
        self.queue_panel.set_cover(
            cover_path_for(self.model[idx].path, self._effective_dest_dir())
        )

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

        self.model.reset_statuses()
        self._start_run(list(range(len(self.model))))

    def _on_retry_failed(self) -> None:
        """Re-run only the failed rows, leaving successes as the user earned them."""
        if self._converting:
            return
        failed = self.model.failed_indices
        if not failed:
            return
        self.model.reset_items(failed)
        self._log(f"[*] Retrying {len(failed)} failed file(s)")
        self._start_run(failed)

    def _start_run(self, indices: list[int]) -> None:
        """Submit the given model rows as one run, recording the mapping."""
        self._batch_indices = list(indices)
        self._batch_sources = [self.model[i].path for i in self._batch_indices]

        self._converting = True
        self._cancel.clear()
        self.queue_panel.rebuild()
        self.controls.set_progress(0)
        self.controls.set_inputs_enabled(False)
        self.controls.set_hifi_enabled(False)
        self.controls.set_retry_enabled(False)
        self.controls.set_convert_button(text="Cancel", enabled=True, danger=True)

        pipeline.start_batch(
            sources=self._batch_sources,
            target_fmt=self.controls.fmt_var.get().lower(),
            mode=("hifi" if self.controls.mode_var.get() == "High-Fidelity"
                  else "standard"),
            extract_cover=self.controls.extract_cover,
            strict_tables=self.controls.strict_tables,
            dest_dir=self._effective_dest_dir(),
            keep_intermediates=self.controls.keep_intermediates,
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
        self.controls.set_retry_enabled(self.model.has_failures)
        # Mode availability depends on the current source/target pair
        self._on_format_change(self.controls.fmt_var.get())
        self._update_convert_button()

    # ==================================================================
    # Log polling — drains the queue and dispatches markers
    # ==================================================================

    def _row_for(self, submitted_idx: int) -> int:
        """Model row for a submitted position, or -1 when the marker is out of
        range for this run (a stale or malformed message)."""
        if 0 <= submitted_idx < len(self._batch_indices):
            return self._batch_indices[submitted_idx]
        return -1

    def _run_progress(self, completed: int) -> float:
        return completed / (len(self._batch_indices) or 1)

    def _poll_log(self) -> None:
        try:
            while True:
                msg = self._log_q.get_nowait()
                marker = markers.parse(msg)

                # Anything the protocol does not recognise - including a
                # malformed control message - is ordinary log text.
                if marker is None:
                    self._log(msg)
                    continue

                # Markers index the submitted list; translate to a model row.
                row = -1 if marker.index is None else self._row_for(marker.index)

                if marker.kind is markers.Kind.FILE_START and row >= 0:
                    self.model.set_running(row)
                    self.queue_panel.render_status()
                    self.controls.set_progress(self._run_progress(marker.index))
                    # Auto-track the preview unless the user pinned a row
                    if self.model.is_auto_tracking:
                        self._preview_cover_for_row(row)
                        self.controls.set_source(self.model[row].path.name)

                elif marker.kind is markers.Kind.FILE_DONE and row >= 0:
                    self.model.set_status(row, "done")
                    self.queue_panel.rebuild()
                    self.controls.set_progress(self._run_progress(marker.index + 1))
                    # The cover may only just have appeared on disk
                    if self.model.is_auto_tracking and self.model.running_idx == row:
                        self._preview_cover_for_row(row)

                elif marker.kind is markers.Kind.FILE_ERROR and row >= 0:
                    # rebuild(), not render_status(): the row gains a reason
                    # subtitle, which changes its layout.
                    self.model.set_status(row, "error", marker.payload)
                    self.queue_panel.rebuild()
                    self.controls.set_progress(self._run_progress(marker.index + 1))

                else:
                    # BATCH_DONE / BATCH_CANCELLED / ERROR / legacy DONE all
                    # mean the run is over.
                    self._finish_conversion()
                    return
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
        cover = cover_path_for(self.model[idx].path, self._effective_dest_dir())
        if cover.exists():
            self._reveal(cover)
        else:
            self._log("[!] No cover extracted for this file yet")

    def _open_output_folder(self) -> None:
        """Open the folder outputs are actually written to.

        With a destination set that is no longer `source.parent`, so this has to
        ask the resolver like every other consumer.
        """
        dest = self._effective_dest_dir()
        if dest is not None:
            self._reveal(dest)
            return
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

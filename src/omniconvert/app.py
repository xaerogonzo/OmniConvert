"""OmniConvert — offline document converter with CustomTkinter GUI.

v0.2: adds drag-and-drop file loading and batch conversion via a scrollable
queue panel. The root window mixes in TkinterDnD.DnDWrapper so the whole
window accepts file drops.
"""

from __future__ import annotations

import os
import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD

from omniconvert.converters import pipeline
from omniconvert.converters.pipeline import sanitize_stem

# ---------------------------------------------------------------------------
# Vendor pandoc auto-detection (portable install via scripts/install_pandoc.py)
# ---------------------------------------------------------------------------

# __file__ is src/omniconvert/app.py — go up to project root
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_VENDOR_PANDOC = _PROJECT_ROOT / "vendor" / "pandoc"
if _VENDOR_PANDOC.exists() and str(_VENDOR_PANDOC) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(_VENDOR_PANDOC) + ";" + os.environ.get("PATH", "")

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

SUPPORTED = {".pdf", ".docx", ".epub", ".md", ".txt"}
FORMATS = ["PDF", "DOCX", "EPUB", "MD", "TXT"]
PANDOC_AVAILABLE = False

# Status icons for the queue rows
STATUS_PENDING = "○"
STATUS_RUNNING = "▶"
STATUS_DONE    = "✓"
STATUS_ERROR   = "✗"

ROW_BG_NORMAL   = "#1e1e1e"
ROW_BG_SELECTED = "#2a4a7a"
ROW_BG_RUNNING  = "#3a3a1a"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _check_pandoc() -> bool:
    try:
        import pypandoc
        pypandoc.get_pandoc_version()
        return True
    except Exception:
        return False


def _make_placeholder(w: int = 120, h: int = 160) -> ImageTk.PhotoImage:
    img = Image.new("RGB", (w, h), "#2b2b2b")
    return ImageTk.PhotoImage(img)


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
        self.TkdndVersion = TkinterDnD._require(self)

        self.title("OmniConvert")
        self.geometry("960x720")
        self.resizable(False, False)

        # ---- State ----
        self._queue: list[Path] = []
        self._queue_status: list[str] = []   # 'pending' | 'running' | 'done' | 'error'
        self._queue_rows: list[dict] = []    # widget refs per row
        self._selected_idx: int = -1         # -1 = follow running file (auto-track)
        self._running_idx: int = -1          # -1 = idle
        self._log_q: queue.Queue = queue.Queue()
        self._converting = False

        self._cover_photo: ImageTk.PhotoImage | None = None
        self._placeholder_photo = _make_placeholder()

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
        self._build_main_content()
        self._build_log_frame()

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
        frame.grid_columnconfigure(2, weight=1)

        ctk.CTkButton(
            frame, text="Browse Files…", width=130, command=self._on_browse_files,
        ).grid(row=0, column=0, padx=(0, 8))

        ctk.CTkButton(
            frame, text="Add Folder…", width=120, command=self._on_add_folder,
        ).grid(row=0, column=1, padx=(0, 12))

        self._file_label = ctk.CTkLabel(
            frame,
            text="No files queued  —  drop PDFs, DOCXs, EPUBs, MDs, TXTs here  (or a folder)",
            anchor="w",
            text_color="gray",
            font=ctk.CTkFont(size=12),
        )
        self._file_label.grid(row=0, column=2, sticky="ew")

    def _build_main_content(self) -> None:
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=2, column=0, sticky="nsew", padx=20, pady=14)
        main.grid_columnconfigure(0, weight=0)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        self._build_queue_panel(main)
        self._build_controls_panel(main)

    def _build_queue_panel(self, parent: ctk.CTkFrame) -> None:
        frame = ctk.CTkFrame(parent, width=300, fg_color="#1e1e1e", corner_radius=10)
        frame.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        frame.grid_propagate(False)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(3, weight=1)

        # Cover thumbnail
        self._cover_label = tk.Label(
            frame, image=self._placeholder_photo, bg="#1e1e1e", cursor="hand2",
        )
        self._cover_label.grid(row=0, column=0, padx=10, pady=(10, 4))
        self._cover_label.bind("<ButtonPress-1>", lambda e: self._open_cover())

        self._dim_label = ctk.CTkLabel(
            frame, text="No cover", text_color="gray", font=ctk.CTkFont(size=11),
        )
        self._dim_label.grid(row=1, column=0, pady=(0, 8))

        # Queue header
        self._queue_header = ctk.CTkLabel(
            frame, text="Queue (empty)", anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self._queue_header.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 4))

        # Scrollable queue list
        self._queue_scroll = ctk.CTkScrollableFrame(
            frame, fg_color="#161616", corner_radius=6,
        )
        self._queue_scroll.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 10))
        self._queue_scroll.grid_columnconfigure(0, weight=1)

    def _build_controls_panel(self, parent: ctk.CTkFrame) -> None:
        frame = ctk.CTkFrame(parent, fg_color="#1e1e1e", corner_radius=10)
        frame.grid(row=0, column=1, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)

        row = 0

        self._source_label = ctk.CTkLabel(
            frame, text="Source: —", anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._source_label.grid(row=row, column=0, sticky="ew", padx=18, pady=(18, 6))
        row += 1

        ctk.CTkLabel(frame, text="", height=1, fg_color="#333").grid(
            row=row, column=0, sticky="ew", padx=18,
        )
        row += 1

        ctk.CTkLabel(frame, text="Convert to:", anchor="w",
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, sticky="w", padx=18, pady=(14, 2),
        )
        row += 1

        self._fmt_var = ctk.StringVar(value="PDF")
        self._fmt_menu = ctk.CTkOptionMenu(
            frame, values=FORMATS, variable=self._fmt_var,
            command=self._on_format_change,
        )
        self._fmt_menu.grid(row=row, column=0, sticky="ew", padx=18, pady=(0, 10))
        row += 1

        ctk.CTkLabel(frame, text="Conversion mode:", anchor="w",
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, sticky="w", padx=18, pady=(4, 2),
        )
        row += 1

        self._mode_var = ctk.StringVar(value="Standard")
        self._mode_seg = ctk.CTkSegmentedButton(
            frame, values=["Standard", "High-Fidelity"], variable=self._mode_var,
            command=self._on_mode_change,
        )
        self._mode_seg.grid(row=row, column=0, sticky="ew", padx=18, pady=(0, 14))
        row += 1

        ctk.CTkLabel(frame, text="Options:", anchor="w",
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, sticky="w", padx=18, pady=(0, 4),
        )
        row += 1

        self._opt_headers = ctk.CTkCheckBox(frame, text="Preserve Headers")
        self._opt_headers.select()
        self._opt_headers.grid(row=row, column=0, sticky="w", padx=28, pady=2)
        row += 1

        self._opt_cover = ctk.CTkCheckBox(frame, text="Extract Cover")
        self._opt_cover.select()
        self._opt_cover.grid(row=row, column=0, sticky="w", padx=28, pady=2)
        row += 1

        self._opt_tables = ctk.CTkCheckBox(frame, text="Strict Table Grid")
        self._opt_tables.select()
        self._opt_tables.grid(row=row, column=0, sticky="w", padx=28, pady=2)
        row += 1

        self._opt_subfolders = ctk.CTkCheckBox(frame, text="Include subfolders")
        self._opt_subfolders.grid(row=row, column=0, sticky="w", padx=28, pady=2)
        row += 1

        frame.grid_rowconfigure(row, weight=1)
        row += 1

        self._convert_btn = ctk.CTkButton(
            frame, text="Convert", height=44,
            font=ctk.CTkFont(size=14, weight="bold"), command=self._on_convert,
        )
        self._convert_btn.grid(row=row, column=0, sticky="ew", padx=18, pady=18)

    def _build_log_frame(self) -> None:
        frame = ctk.CTkFrame(self, fg_color="#161616", corner_radius=10)
        frame.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 14))
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text="Log", anchor="w",
                     font=ctk.CTkFont(size=11), text_color="gray").grid(
            row=0, column=0, sticky="w", padx=12, pady=(6, 0),
        )

        self._log_box = ctk.CTkTextbox(
            frame, height=130,
            font=ctk.CTkFont(family="Consolas", size=11),
            state="disabled", wrap="word",
        )
        self._log_box.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))

    # ==================================================================
    # Input handlers (drop / browse / folder add) — all guard against mid-batch
    # ==================================================================

    def _on_drop(self, event):
        """Handle file/folder drop events from tkinterdnd2."""
        if self._converting:
            self._on_drop_leave(event)
            self._log("[!] Batch in progress — drop rejected. Wait for completion.")
            return
        raw = self.tk.splitlist(event.data)
        paths = [Path(p) for p in raw]
        self._on_drop_leave(event)  # restore label color/text
        expanded: list[Path] = []
        for p in paths:
            if p.is_dir():
                expanded.extend(self._scan_folder(p))
            elif p.is_file() and p.suffix.lower() in SUPPORTED:
                expanded.append(p)
        if not expanded:
            self._log("[!] No supported files in drop")
            return
        self._set_queue(expanded)

    def _on_drop_enter(self, event):
        self._file_label.configure(text="Drop to load…", text_color="#4a9eff")
        return event.action

    def _on_drop_leave(self, event):
        self._refresh_file_label()
        return event.action

    def _on_browse_files(self):
        if self._converting:
            self._log("[!] Batch in progress — browse rejected.")
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
        if not paths:
            return
        valid = [Path(p) for p in paths if Path(p).suffix.lower() in SUPPORTED]
        if valid:
            self._set_queue(valid)

    def _on_add_folder(self):
        if self._converting:
            self._log("[!] Batch in progress — folder add rejected.")
            return
        folder = filedialog.askdirectory(title="Select a folder to scan")
        if not folder:
            return
        files = self._scan_folder(Path(folder))
        if not files:
            self._log(f"[!] No supported files in {folder}")
            return
        self._set_queue(files)

    def _scan_folder(self, folder: Path) -> list[Path]:
        recursive = bool(self._opt_subfolders.get())
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
    # Queue state management
    # ==================================================================

    def _set_queue(self, paths: list[Path]) -> None:
        """Replace the entire queue with `paths`. Resets selection and previews."""
        self._queue = list(paths)
        self._queue_status = ["pending"] * len(paths)
        self._selected_idx = -1
        self._running_idx = -1
        self._rebuild_queue_rows()
        self._update_queue_header()
        self._refresh_file_label()
        if paths:
            self._source_label.configure(text=f"Source: {paths[0].name}")
            self._preview_cover_for_row(0)
            self._log(f"[*] Queued {len(paths)} file(s)")
        else:
            self._source_label.configure(text="Source: —")
            self._set_cover(None)
        self._on_format_change(self._fmt_var.get())
        self._update_convert_button()

    def _update_queue_header(self) -> None:
        n = len(self._queue)
        text = "Queue (empty)" if n == 0 else f"Queue ({n} file{'s' if n != 1 else ''})"
        self._queue_header.configure(text=text)

    def _refresh_file_label(self) -> None:
        """Repaint the drop-zone status label based on current queue state."""
        if not self._queue:
            self._file_label.configure(
                text="No files queued  —  drop PDFs, DOCXs, EPUBs, MDs, TXTs here  (or a folder)",
                text_color="gray",
            )
        elif len(self._queue) == 1:
            p = self._queue[0]
            size_mb = p.stat().st_size / (1024 * 1024)
            self._file_label.configure(
                text=f"{p.name}  ({size_mb:.1f} MB)", text_color="white",
            )
        else:
            self._file_label.configure(
                text=f"{len(self._queue)} files queued",
                text_color="white",
            )

    def _rebuild_queue_rows(self) -> None:
        """Wipe and re-render every queue row. Called when queue changes."""
        for w in self._queue_scroll.winfo_children():
            w.destroy()
        self._queue_rows = []

        for idx, path in enumerate(self._queue):
            row = ctk.CTkFrame(self._queue_scroll, fg_color=ROW_BG_NORMAL, corner_radius=4)
            row.grid(row=idx, column=0, sticky="ew", padx=2, pady=1)
            row.grid_columnconfigure(1, weight=1)

            icon_lbl = ctk.CTkLabel(row, text=STATUS_PENDING, width=20,
                                    font=ctk.CTkFont(size=12))
            icon_lbl.grid(row=0, column=0, padx=(6, 4), pady=4)

            name_lbl = ctk.CTkLabel(row, text=path.name, anchor="w",
                                    font=ctk.CTkFont(size=11))
            name_lbl.grid(row=0, column=1, sticky="ew", padx=(0, 4))

            size_kb = path.stat().st_size / 1024
            size_str = (f"{size_kb / 1024:.1f} MB" if size_kb >= 1024
                        else f"{size_kb:.0f} KB")
            size_lbl = ctk.CTkLabel(row, text=size_str, text_color="gray",
                                    font=ctk.CTkFont(size=10))
            size_lbl.grid(row=0, column=2, padx=(0, 8))

            # Click anywhere on the row → select it
            for w in (row, icon_lbl, name_lbl, size_lbl):
                w.bind("<Button-1>", lambda e, i=idx: self._on_queue_row_click(i))

            self._queue_rows.append({
                "frame": row, "icon": icon_lbl, "name": name_lbl, "size": size_lbl,
            })

    def _render_queue_status(self) -> None:
        """Refresh icon + row background for every row based on status + selection."""
        for idx, row_widgets in enumerate(self._queue_rows):
            status = self._queue_status[idx]
            icon = {
                "pending": STATUS_PENDING, "running": STATUS_RUNNING,
                "done":    STATUS_DONE,    "error":   STATUS_ERROR,
            }.get(status, STATUS_PENDING)
            row_widgets["icon"].configure(text=icon)

            # Background priority: explicit user selection > running > normal
            if idx == self._selected_idx:
                bg = ROW_BG_SELECTED
            elif status == "running":
                bg = ROW_BG_RUNNING
            else:
                bg = ROW_BG_NORMAL
            row_widgets["frame"].configure(fg_color=bg)

    def _on_queue_row_click(self, idx: int) -> None:
        """User clicked a queue row. Click on currently-running row re-arms auto-track."""
        if idx == self._running_idx and self._converting:
            self._selected_idx = -1  # re-arm auto-tracking
        else:
            self._selected_idx = idx
        self._render_queue_status()
        self._preview_cover_for_row(idx)

    def _preview_cover_for_row(self, idx: int) -> None:
        """Try to display the cover image for queue row idx."""
        if not (0 <= idx < len(self._queue)):
            return
        src = self._queue[idx]
        # Cover filename mirrors pipeline._intermediate_paths()
        src_ext = src.suffix.lower().lstrip(".")
        stem = sanitize_stem(src.stem)
        cover = src.parent / f"{stem}_{src_ext}_cover.png"
        if cover.exists():
            self._set_cover(cover)
        else:
            self._set_cover(None)

    # ==================================================================
    # Format / mode controls
    # ==================================================================

    def _on_format_change(self, value: str) -> None:
        """Re-evaluate whether High-Fidelity is available based on src/target pair."""
        fmt = value.lower()
        src_ext = self._queue[0].suffix.lower() if self._queue else ""

        hifi_valid = (
            (src_ext == ".pdf"  and fmt == "docx")
            or (src_ext == ".docx" and fmt == "pdf")
        )
        if not hifi_valid:
            self._mode_var.set("Standard")
            self._mode_seg.configure(state="disabled")
        else:
            self._mode_seg.configure(state="normal")
        self._update_convert_button()

    def _on_mode_change(self, value: str) -> None:
        self._update_convert_button()

    # ==================================================================
    # Convert button
    # ==================================================================

    def _on_convert(self) -> None:
        if self._converting or not self._queue:
            return

        self._converting = True
        self._convert_btn.configure(state="disabled", text="Converting…")
        self._fmt_menu.configure(state="disabled")
        self._mode_seg.configure(state="disabled")

        # Reset row statuses
        self._queue_status = ["pending"] * len(self._queue)
        self._running_idx = -1
        self._selected_idx = -1
        self._render_queue_status()

        pipeline.start_batch(
            sources=self._queue,
            target_fmt=self._fmt_var.get().lower(),
            mode=("hifi" if self._mode_var.get() == "High-Fidelity" else "standard"),
            extract_cover=bool(self._opt_cover.get()),
            log_q=self._log_q,
        )
        self.after(100, self._poll_log)

    def _update_convert_button(self) -> None:
        """Update label and enabled state. Call after queue/format/mode changes."""
        if self._converting:
            return

        fmt = self._fmt_var.get().lower()
        needs_pandoc = fmt in {"docx", "epub", "txt"}
        mode_is_hifi = self._mode_var.get() == "High-Fidelity"

        n = len(self._queue)
        if n == 0:
            label = "Convert"
        elif n == 1:
            label = "Convert"
        else:
            label = f"Convert Batch ({n})"

        enabled = (
            n > 0
            and (PANDOC_AVAILABLE or not needs_pandoc or mode_is_hifi)
        )
        self._convert_btn.configure(
            state="normal" if enabled else "disabled",
            text=label,
        )

    def _finish_conversion(self) -> None:
        """Common teardown when a batch finishes (success or error)."""
        self._converting = False
        self._running_idx = -1
        self._fmt_menu.configure(state="normal")
        # Mode segmented button state depends on current format pair
        self._on_format_change(self._fmt_var.get())
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
                    self._queue_status[n] = "running"
                    self._running_idx = n
                    self._render_queue_status()
                    # Auto-track cover preview only if user hasn't pinned a selection
                    if self._selected_idx == -1:
                        self._preview_cover_for_row(n)
                        self._source_label.configure(text=f"Source: {self._queue[n].name}")

                elif msg.startswith("__FILE_DONE__"):
                    n = int(msg[len("__FILE_DONE__"):])
                    self._queue_status[n] = "done"
                    self._render_queue_status()
                    # Refresh cover for the running file (it might just have appeared)
                    if self._selected_idx == -1 and self._running_idx == n:
                        self._preview_cover_for_row(n)

                elif msg.startswith("__FILE_ERROR__"):
                    n = int(msg[len("__FILE_ERROR__"):])
                    self._queue_status[n] = "error"
                    self._render_queue_status()

                elif msg == "__BATCH_DONE__":
                    self._finish_conversion()
                    return

                elif msg.startswith("__DONE__"):
                    # Legacy single-file marker (unused in batch path, kept for compat)
                    self._finish_conversion()
                    return

                elif msg == "__ERROR__":
                    self._finish_conversion()
                    return

                else:
                    self._log(msg)
        except queue.Empty:
            pass

        if self._converting:
            self.after(100, self._poll_log)

    def _log(self, text: str) -> None:
        self._log_box.configure(state="normal")
        self._log_box.insert("end", text + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    # ==================================================================
    # Cover preview
    # ==================================================================

    def _set_cover(self, cover_path: Path | None) -> None:
        if cover_path and cover_path.exists():
            img = Image.open(cover_path)
            w, h = img.size
            max_w, max_h = 120, 160
            scale = min(max_w / w, max_h / h)
            new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
            img = img.resize((new_w, new_h), Image.LANCZOS)
            self._cover_photo = ImageTk.PhotoImage(img)
            self._cover_label.configure(image=self._cover_photo)
            self._dim_label.configure(
                text=f"{w} × {h} px  |  {cover_path.stat().st_size // 1024} KB"
            )
        else:
            self._cover_label.configure(image=self._placeholder_photo)
            self._dim_label.configure(text="No cover")

    def _open_cover(self) -> None:
        """Open the currently-previewed cover in the system default viewer."""
        idx = self._selected_idx if self._selected_idx != -1 else self._running_idx
        if idx == -1 and self._queue:
            idx = 0
        if not (0 <= idx < len(self._queue)):
            return
        import subprocess
        src = self._queue[idx]
        src_ext = src.suffix.lower().lstrip(".")
        stem = sanitize_stem(src.stem)
        cover = src.parent / f"{stem}_{src_ext}_cover.png"
        if cover.exists():
            subprocess.Popen(["explorer", str(cover)])

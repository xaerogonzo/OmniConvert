"""Queue actions and the output destination.

Owns two pieces of display state that `app.py` used to reach into by hand: the
queue summary line (which doubles as the drag-and-drop hint) and the output
destination.

The destination is stated explicitly — "Output: source folder" rather than an
empty label left to imply it — because a blank field is indistinguishable from
"not set yet".
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import customtkinter as ctk

_MUTED = {"fg_color": "#3a3a3a", "hover_color": "#4a4a4a"}

_EMPTY_HINT = ("No files queued  —  drop PDFs, DOCXs, EPUBs, MDs, TXTs here  "
               "(or a folder)")


class ToolbarPanel(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        *,
        on_browse: Callable[[], None],
        on_add_folder: Callable[[], None],
        on_clear: Callable[[], None],
        on_open_folder: Callable[[], None],
        on_choose_output: Callable[[], None],
        on_reset_output: Callable[[], None],
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(4, weight=1)

        ctk.CTkButton(self, text="Browse Files…", width=120,
                      command=on_browse).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(self, text="Add Folder…", width=110,
                      command=on_add_folder).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(self, text="Clear", width=70, **_MUTED,
                      command=on_clear).grid(row=0, column=2, padx=(0, 8))
        ctk.CTkButton(self, text="Open Folder", width=110, **_MUTED,
                      command=on_open_folder).grid(row=0, column=3, padx=(0, 12))

        self._summary = ctk.CTkLabel(
            self, text=_EMPTY_HINT, anchor="w", text_color="gray",
            font=ctk.CTkFont(size=12),
        )
        self._summary.grid(row=0, column=4, sticky="ew")

        ctk.CTkButton(self, text="Output to…", width=120,
                      command=on_choose_output).grid(row=1, column=0, padx=(0, 8),
                                                     pady=(8, 0))
        ctk.CTkButton(self, text="Reset", width=70, **_MUTED,
                      command=on_reset_output).grid(row=1, column=1, padx=(0, 12),
                                                    pady=(8, 0), sticky="w")

        self._dest = ctk.CTkLabel(
            self, text="Output: source folder", anchor="w", text_color="gray",
            font=ctk.CTkFont(size=12),
        )
        self._dest.grid(row=1, column=2, columnspan=3, sticky="ew", pady=(8, 0))

    # ---- queue summary / drop hint -----------------------------------
    def set_queue_summary(self, paths: list[Path]) -> None:
        if not paths:
            self._summary.configure(text=_EMPTY_HINT, text_color="gray")
            return
        if len(paths) == 1:
            try:
                size = f"  ({paths[0].stat().st_size / (1024 * 1024):.1f} MB)"
            except OSError:            # deleted between queueing and rendering
                size = ""
            self._summary.configure(text=f"{paths[0].name}{size}",
                                    text_color="white")
            return
        self._summary.configure(text=f"{len(paths)} files queued",
                                text_color="white")

    def show_drop_hint(self) -> None:
        self._summary.configure(text="Drop to load…", text_color="#4a9eff")

    # ---- output destination ------------------------------------------
    def set_output_destination(self, dest: Path | None) -> None:
        self._dest.configure(
            text="Output: source folder" if dest is None else f"Output: {dest}"
        )

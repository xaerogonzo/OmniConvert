"""Cover preview plus the scrollable file queue.

Renders from a QueueModel; it holds no queue state of its own.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable

import customtkinter as ctk
from PIL import Image, ImageTk

from .constants import (
    PANEL_BG,
    ROW_BG_NORMAL,
    ROW_BG_RUNNING,
    ROW_BG_SELECTED,
    SCROLL_BG,
    STATUS_ICONS,
    STATUS_PENDING,
)
from .queue_model import QueueModel

_COVER_MAX = (120, 160)


def _make_placeholder(w: int = 120, h: int = 160) -> ImageTk.PhotoImage:
    return ImageTk.PhotoImage(Image.new("RGB", (w, h), "#2b2b2b"))


def _size_label(path: Path) -> str:
    try:
        kb = path.stat().st_size / 1024
    except OSError:          # file vanished between queueing and rendering
        return "—"
    return f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"


class QueuePanel(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        model: QueueModel,
        on_row_click: Callable[[int], None],
        on_cover_click: Callable[[], None],
    ) -> None:
        super().__init__(parent, width=300, fg_color=PANEL_BG, corner_radius=10)
        self._model = model
        self._on_row_click = on_row_click

        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._placeholder = _make_placeholder()
        self._cover_photo: ImageTk.PhotoImage | None = None

        self._cover_label = tk.Label(
            self, image=self._placeholder, bg=PANEL_BG, cursor="hand2",
        )
        self._cover_label.grid(row=0, column=0, padx=10, pady=(10, 4))
        self._cover_label.bind("<ButtonPress-1>", lambda e: on_cover_click())

        self._dim_label = ctk.CTkLabel(
            self, text="No cover", text_color="gray", font=ctk.CTkFont(size=11),
        )
        self._dim_label.grid(row=1, column=0, pady=(0, 8))

        self._header = ctk.CTkLabel(
            self, text="Queue (empty)", anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self._header.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 4))

        self._scroll = ctk.CTkScrollableFrame(self, fg_color=SCROLL_BG, corner_radius=6)
        self._scroll.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 10))
        self._scroll.grid_columnconfigure(0, weight=1)

        self._rows: list[dict] = []

    # ---- rendering ---------------------------------------------------
    def rebuild(self) -> None:
        """Wipe and re-render every row. Call when the queue contents change."""
        for w in self._scroll.winfo_children():
            w.destroy()
        self._rows = []

        for idx, item in enumerate(self._model):
            row = ctk.CTkFrame(self._scroll, fg_color=ROW_BG_NORMAL, corner_radius=4)
            row.grid(row=idx, column=0, sticky="ew", padx=2, pady=1)
            row.grid_columnconfigure(1, weight=1)

            icon = ctk.CTkLabel(row, text=STATUS_PENDING, width=20,
                                font=ctk.CTkFont(size=12))
            icon.grid(row=0, column=0, padx=(6, 4), pady=4)

            name = ctk.CTkLabel(row, text=item.path.name, anchor="w",
                                font=ctk.CTkFont(size=11))
            name.grid(row=0, column=1, sticky="ew", padx=(0, 4))

            size = ctk.CTkLabel(row, text=_size_label(item.path), text_color="gray",
                                font=ctk.CTkFont(size=10))
            size.grid(row=0, column=2, padx=(0, 8))

            for w in (row, icon, name, size):
                w.bind("<Button-1>", lambda e, i=idx: self._on_row_click(i))

            self._rows.append({"frame": row, "icon": icon, "name": name, "size": size})

        self.refresh_header()
        self.render_status()

    def render_status(self) -> None:
        """Refresh icon + background for every row from the model."""
        for idx, widgets in enumerate(self._rows):
            if idx >= len(self._model):
                continue
            status = self._model[idx].status
            widgets["icon"].configure(text=STATUS_ICONS.get(status, STATUS_PENDING))

            # Background priority: explicit user selection > running > normal
            if idx == self._model.selected_idx:
                bg = ROW_BG_SELECTED
            elif status == "running":
                bg = ROW_BG_RUNNING
            else:
                bg = ROW_BG_NORMAL
            widgets["frame"].configure(fg_color=bg)

    def refresh_header(self) -> None:
        n = len(self._model)
        self._header.configure(
            text="Queue (empty)" if n == 0
            else f"Queue ({n} file{'s' if n != 1 else ''})"
        )

    # ---- cover preview -----------------------------------------------
    def set_cover(self, cover_path: Path | None) -> None:
        if cover_path and cover_path.exists():
            try:
                img = Image.open(cover_path)
                w, h = img.size
                scale = min(_COVER_MAX[0] / w, _COVER_MAX[1] / h)
                img = img.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS
                )
                self._cover_photo = ImageTk.PhotoImage(img)
                self._cover_label.configure(image=self._cover_photo)
                self._dim_label.configure(
                    text=f"{w} × {h} px  |  {cover_path.stat().st_size // 1024} KB"
                )
                return
            except (OSError, ValueError):
                pass  # unreadable/corrupt cover - fall through to placeholder
        self._cover_label.configure(image=self._placeholder)
        self._dim_label.configure(text="No cover")

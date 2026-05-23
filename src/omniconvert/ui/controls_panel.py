"""Format / mode / options controls plus the convert button and progress bar."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from .constants import FORMATS, PANEL_BG


class ControlsPanel(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        on_format_change: Callable[[str], None],
        on_mode_change: Callable[[str], None],
        on_convert: Callable[[], None],
    ) -> None:
        super().__init__(parent, fg_color=PANEL_BG, corner_radius=10)
        self.grid_columnconfigure(0, weight=1)

        row = 0

        self._source_label = ctk.CTkLabel(
            self, text="Source: —", anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._source_label.grid(row=row, column=0, sticky="ew", padx=18, pady=(18, 6))
        row += 1

        ctk.CTkLabel(self, text="", height=1, fg_color="#333").grid(
            row=row, column=0, sticky="ew", padx=18,
        )
        row += 1

        ctk.CTkLabel(self, text="Convert to:", anchor="w",
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, sticky="w", padx=18, pady=(14, 2),
        )
        row += 1

        self.fmt_var = ctk.StringVar(value="PDF")
        self._fmt_menu = ctk.CTkOptionMenu(
            self, values=FORMATS, variable=self.fmt_var, command=on_format_change,
        )
        self._fmt_menu.grid(row=row, column=0, sticky="ew", padx=18, pady=(0, 10))
        row += 1

        ctk.CTkLabel(self, text="Conversion mode:", anchor="w",
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, sticky="w", padx=18, pady=(4, 2),
        )
        row += 1

        self.mode_var = ctk.StringVar(value="Standard")
        self._mode_seg = ctk.CTkSegmentedButton(
            self, values=["Standard", "High-Fidelity"], variable=self.mode_var,
            command=on_mode_change,
        )
        self._mode_seg.grid(row=row, column=0, sticky="ew", padx=18, pady=(0, 14))
        row += 1

        ctk.CTkLabel(self, text="Options:", anchor="w",
                     font=ctk.CTkFont(size=12)).grid(
            row=row, column=0, sticky="w", padx=18, pady=(0, 4),
        )
        row += 1

        self._opt_cover = ctk.CTkCheckBox(self, text="Extract Cover")
        self._opt_cover.select()
        self._opt_cover.grid(row=row, column=0, sticky="w", padx=28, pady=2)
        row += 1

        # Drives ruled table borders on the MD → PDF path (from_markdown._to_pdf)
        self._opt_tables = ctk.CTkCheckBox(self, text="Strict Table Grid")
        self._opt_tables.select()
        self._opt_tables.grid(row=row, column=0, sticky="w", padx=28, pady=2)
        row += 1

        self._opt_subfolders = ctk.CTkCheckBox(self, text="Include subfolders")
        self._opt_subfolders.grid(row=row, column=0, sticky="w", padx=28, pady=2)
        row += 1

        self.grid_rowconfigure(row, weight=1)
        row += 1

        self._progress = ctk.CTkProgressBar(self, height=8)
        self._progress.set(0)
        self._progress.grid(row=row, column=0, sticky="ew", padx=18, pady=(0, 4))
        row += 1

        self._convert_btn = ctk.CTkButton(
            self, text="Convert", height=44,
            font=ctk.CTkFont(size=14, weight="bold"), command=on_convert,
        )
        self._convert_btn.grid(row=row, column=0, sticky="ew", padx=18, pady=(4, 18))

    # ---- option accessors --------------------------------------------
    @property
    def extract_cover(self) -> bool:
        return bool(self._opt_cover.get())

    @property
    def strict_tables(self) -> bool:
        return bool(self._opt_tables.get())

    @property
    def include_subfolders(self) -> bool:
        return bool(self._opt_subfolders.get())

    # ---- display -----------------------------------------------------
    def set_source(self, text: str) -> None:
        self._source_label.configure(text=f"Source: {text}")

    def set_progress(self, fraction: float) -> None:
        self._progress.set(max(0.0, min(1.0, fraction)))

    def set_convert_button(self, *, text: str, enabled: bool = True,
                           danger: bool = False) -> None:
        colors = {"fg_color": "#8a2b2b", "hover_color": "#a33"} if danger else {
            "fg_color": ctk.ThemeManager.theme["CTkButton"]["fg_color"],
            "hover_color": ctk.ThemeManager.theme["CTkButton"]["hover_color"],
        }
        self._convert_btn.configure(
            text=text, state="normal" if enabled else "disabled", **colors
        )

    def set_inputs_enabled(self, enabled: bool) -> None:
        """Lock the format menu while a batch runs; mode is handled separately."""
        self._fmt_menu.configure(state="normal" if enabled else "disabled")

    def set_hifi_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.mode_var.set("Standard")
        self._mode_seg.configure(state="normal" if enabled else "disabled")

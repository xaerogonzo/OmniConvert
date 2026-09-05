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
        on_retry: Callable[[], None],
    ) -> None:
        super().__init__(parent, fg_color=PANEL_BG, corner_radius=10)
        self.grid_columnconfigure(0, weight=1)

        # High-Fidelity only applies to the PDF/DOCX pairs, so the live mode is
        # forced to Standard whenever the current pair cannot use it. That would
        # otherwise erase a saved preference the moment the app starts with an
        # empty queue, so the user's actual choice is tracked separately.
        self._preferred_mode = "Standard"
        self._on_mode_change = on_mode_change

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
            command=self._mode_changed,
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

        # On by default: docs/ARCHITECTURE.md documents keeping the hub markdown
        # and image folder as deliberate, for AI-pipeline use.
        self._opt_keep = ctk.CTkCheckBox(self, text="Keep intermediate files")
        self._opt_keep.select()
        self._opt_keep.grid(row=row, column=0, sticky="w", padx=28, pady=2)
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
        self._convert_btn.grid(row=row, column=0, sticky="ew", padx=18, pady=(4, 4))
        row += 1

        self._retry_btn = ctk.CTkButton(
            self, text="Retry Failed", height=30, state="disabled",
            fg_color="#3a3a3a", hover_color="#4a4a4a",
            font=ctk.CTkFont(size=12), command=on_retry,
        )
        self._retry_btn.grid(row=row, column=0, sticky="ew", padx=18, pady=(0, 18))

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

    @property
    def keep_intermediates(self) -> bool:
        return bool(self._opt_keep.get())

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

    def set_retry_enabled(self, enabled: bool) -> None:
        """Available only while idle and only while failures remain, so repeated
        retries of a stubbornly-failing file keep working."""
        self._retry_btn.configure(state="normal" if enabled else "disabled")

    def set_inputs_enabled(self, enabled: bool) -> None:
        """Lock the format menu while a batch runs; mode is handled separately."""
        self._fmt_menu.configure(state="normal" if enabled else "disabled")

    def _mode_changed(self, value: str) -> None:
        """Only a deliberate click updates the remembered preference."""
        self._preferred_mode = value
        self._on_mode_change(value)

    @property
    def preferred_mode(self) -> str:
        """The mode to persist - the user's choice, not a forced fallback."""
        return self._preferred_mode

    def set_preferred_mode(self, mode: str) -> None:
        self._preferred_mode = mode

    def set_options(self, *, extract_cover=None, strict_tables=None,
                    include_subfolders=None, keep_intermediates=None) -> None:
        for box, value in ((self._opt_cover, extract_cover),
                           (self._opt_tables, strict_tables),
                           (self._opt_subfolders, include_subfolders),
                           (self._opt_keep, keep_intermediates)):
            if value is None:
                continue
            box.select() if value else box.deselect()

    def set_hifi_enabled(self, enabled: bool) -> None:
        # Restore the preference when the pair allows it; force Standard when it
        # does not, without forgetting what the user asked for.
        self.mode_var.set(self._preferred_mode if enabled else "Standard")
        self._mode_seg.configure(state="normal" if enabled else "disabled")

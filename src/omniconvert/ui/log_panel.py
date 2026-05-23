"""Scrolling log textbox.

Only ever touched from the main thread: the pipeline posts strings to a
queue.Queue and OmniConvertApp._poll_log drains it via `after()`.
"""

from __future__ import annotations

import customtkinter as ctk

from .constants import SCROLL_BG


class LogPanel(ctk.CTkFrame):
    def __init__(self, parent) -> None:
        super().__init__(parent, fg_color=SCROLL_BG, corner_radius=10)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Log", anchor="w",
            font=ctk.CTkFont(size=11), text_color="gray",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(6, 0))

        self._box = ctk.CTkTextbox(
            self, height=130,
            font=ctk.CTkFont(family="Consolas", size=11),
            state="disabled", wrap="word",
        )
        self._box.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))

    def log(self, text: str) -> None:
        self._box.configure(state="normal")
        self._box.insert("end", text + "\n")
        self._box.see("end")
        self._box.configure(state="disabled")

    def clear(self) -> None:
        self._box.configure(state="normal")
        self._box.delete("1.0", "end")
        self._box.configure(state="disabled")

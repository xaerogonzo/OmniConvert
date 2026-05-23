"""Shared constants for the OmniConvert GUI.

Kept in their own module so the panels can import them without reaching back
into `app`, which would be circular.
"""

SUPPORTED = {".pdf", ".docx", ".epub", ".md", ".txt"}
FORMATS = ["PDF", "DOCX", "EPUB", "MD", "TXT"]

# Formats that can only be produced by pandoc (Standard mode).
PANDOC_TARGETS = {"docx", "epub", "txt"}

# Status icons for the queue rows
STATUS_PENDING = "○"
STATUS_RUNNING = "▶"
STATUS_DONE    = "✓"
STATUS_ERROR   = "✗"

STATUS_ICONS = {
    "pending": STATUS_PENDING,
    "running": STATUS_RUNNING,
    "done":    STATUS_DONE,
    "error":   STATUS_ERROR,
}

ROW_BG_NORMAL   = "#1e1e1e"
ROW_BG_SELECTED = "#2a4a7a"
ROW_BG_RUNNING  = "#3a3a1a"

PANEL_BG = "#1e1e1e"
SCROLL_BG = "#161616"

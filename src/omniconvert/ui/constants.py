"""Shared constants for the OmniConvert GUI.

Kept in their own module so the panels can import them without reaching back
into `app`, which would be circular.
"""

# The format vocabulary lives in omniconvert.formats so settings validation can
# import it without pulling in CustomTkinter; re-exported here for the panels.
from omniconvert.formats import (  # noqa: F401
    FORMATS,
    MODES,
    PANDOC_TARGETS,
    SUPPORTED,
)

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

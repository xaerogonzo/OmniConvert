"""Tk-free state for the conversion queue.

Holding this outside the widget class is what makes the queue's rules testable
without a display. The panel renders from a model; it never owns the state.

Selection rule (unchanged from v0.2.0): `selected_idx == -1` means "follow the
running file". Clicking any other row pins the preview to it; clicking the row
that is currently running re-arms auto-tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

Status = str  # "pending" | "running" | "done" | "error"


@dataclass
class QueueItem:
    path: Path
    status: Status = "pending"


@dataclass
class QueueModel:
    items: list[QueueItem] = field(default_factory=list)
    selected_idx: int = -1   # -1 = auto-track the running row
    running_idx: int = -1    # -1 = idle

    # ---- container protocol ------------------------------------------
    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, idx: int) -> QueueItem:
        return self.items[idx]

    def __bool__(self) -> bool:
        return bool(self.items)

    @property
    def paths(self) -> list[Path]:
        return [i.path for i in self.items]

    # ---- mutation ----------------------------------------------------
    def add(self, paths: list[Path]) -> int:
        """Append `paths`, skipping ones already queued. Returns how many landed.

        Deduplication compares resolved paths so the same file reached through a
        relative path, a different case, or a symlink is only queued once.
        """
        seen = {self._key(i.path) for i in self.items}
        added = 0
        for p in paths:
            key = self._key(p)
            if key in seen:
                continue
            seen.add(key)
            self.items.append(QueueItem(path=p))
            added += 1
        return added

    def clear(self) -> None:
        self.items.clear()
        self.selected_idx = -1
        self.running_idx = -1

    def remove(self, idx: int) -> None:
        if not 0 <= idx < len(self.items):
            return
        del self.items[idx]
        # Keep the two cursors pointing at the same logical rows.
        self.selected_idx = self._shift(self.selected_idx, idx)
        self.running_idx = self._shift(self.running_idx, idx)

    def reset_statuses(self) -> None:
        """Called at the start of a run: every row back to pending, cursors idle."""
        for item in self.items:
            item.status = "pending"
        self.selected_idx = -1
        self.running_idx = -1

    def set_status(self, idx: int, status: Status) -> None:
        if 0 <= idx < len(self.items):
            self.items[idx].status = status

    def set_running(self, idx: int) -> None:
        self.set_status(idx, "running")
        self.running_idx = idx

    # ---- selection ---------------------------------------------------
    def select(self, idx: int, *, converting: bool) -> None:
        """Handle a click on row `idx`.

        Clicking the row that is currently converting re-arms auto-tracking
        rather than pinning to it, so the preview keeps following the worker.
        """
        if idx == self.running_idx and converting:
            self.selected_idx = -1
        else:
            self.selected_idx = idx

    @property
    def is_auto_tracking(self) -> bool:
        return self.selected_idx == -1

    @property
    def preview_idx(self) -> int:
        """Which row's cover should be on screen: the pin, else the runner, else the top."""
        if self.selected_idx != -1:
            return self.selected_idx
        if self.running_idx != -1:
            return self.running_idx
        return 0 if self.items else -1

    # ---- helpers -----------------------------------------------------
    @staticmethod
    def _key(p: Path) -> str:
        try:
            return str(p.resolve()).lower()
        except OSError:            # unreachable network path, etc.
            return str(p).lower()

    @staticmethod
    def _shift(cursor: int, removed: int) -> int:
        if cursor == -1:
            return -1
        if cursor == removed:
            return -1
        return cursor - 1 if cursor > removed else cursor

"""Persisted user preferences.

Stores what the user *chose*, never what a run was doing: no queue contents, no
selection, no statuses. "Remember my preferences" must not quietly become
"restore my previous job".

Two rules make the file safe to evolve and safe to trust:

* **Versioned.** A file from a future version is ignored wholesale rather than
  half-read. Without this, the loader accretes compatibility hacks every time a
  field is added or dropped.
* **Field-level tolerance.** One corrupt value resets that value only. Throwing
  away every valid neighbouring preference because one key is malformed is worse
  than the corruption.

`load()` must never prevent the app from starting, so every failure path here
ends in a default rather than an exception. This module is Tk-free.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from omniconvert.formats import FORMATS, MODES

CURRENT_VERSION = 1

_APP_DIR = "OmniConvert"
_FILE_NAME = "settings.json"

#: "960x720", optionally with a "+x+y" position.
_GEOMETRY_RE = re.compile(r"^\d{1,5}x\d{1,5}([+-]\d{1,5}[+-]\d{1,5})?$")


@dataclass
class Settings:
    version: int = CURRENT_VERSION
    target_fmt: str = "PDF"
    mode: str = "Standard"
    extract_cover: bool = True
    strict_tables: bool = True
    include_subfolders: bool = False
    keep_intermediates: bool = True
    dest_dir: Path | None = None
    geometry: str | None = None

    def effective_dest_dir(self) -> Path | None:
        """The saved destination only if it is still usable.

        A removable drive or network share can be gone by the next launch, and a
        stale path would fail every conversion. One helper so no caller invents
        its own interpretation.
        """
        if self.dest_dir is not None and self.dest_dir.is_dir():
            return self.dest_dir
        return None


def config_path() -> Path:
    """Where preferences live.

    Deliberately NOT derived from `__file__`: a frozen Nuitka executable must
    never write into its own install directory, which is commonly read-only.
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / _APP_DIR / _FILE_NAME


# ---------------------------------------------------------------------------
# Loading - every branch ends in a usable Settings
# ---------------------------------------------------------------------------

def _choice(value, allowed, fallback: str) -> str:
    return value if isinstance(value, str) and value in allowed else fallback


def _flag(value, fallback: bool) -> bool:
    # Strictly bool: JSON "true"/1/"banana" are all corruption, not intent.
    return value if isinstance(value, bool) else fallback


def _directory(value) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return Path(value)
    except (ValueError, OSError):        # embedded NULs, absurd length
        return None


def _geometry(value) -> str | None:
    if isinstance(value, str) and _GEOMETRY_RE.match(value):
        return value
    return None


def load(path: Path | None = None) -> Settings:
    """Read preferences, falling back per field. Never raises."""
    path = path or config_path()
    defaults = Settings()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return defaults                  # absent, unreadable or not JSON

    if not isinstance(raw, dict):
        return defaults

    version = raw.get("version")
    if not isinstance(version, int) or version > CURRENT_VERSION:
        # Written by a newer OmniConvert: its fields may mean something else.
        return defaults

    # Unknown keys are ignored by construction - only known fields are read.
    return replace(
        defaults,
        target_fmt=_choice(raw.get("target_fmt"), FORMATS, defaults.target_fmt),
        mode=_choice(raw.get("mode"), MODES, defaults.mode),
        extract_cover=_flag(raw.get("extract_cover"), defaults.extract_cover),
        strict_tables=_flag(raw.get("strict_tables"), defaults.strict_tables),
        include_subfolders=_flag(raw.get("include_subfolders"),
                                 defaults.include_subfolders),
        keep_intermediates=_flag(raw.get("keep_intermediates"),
                                 defaults.keep_intermediates),
        dest_dir=_directory(raw.get("dest_dir")),
        geometry=_geometry(raw.get("geometry")),
    )


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def save(settings: Settings, path: Path | None = None) -> bool:
    """Write preferences atomically. Returns False instead of raising.

    Called on window close, where an exception would turn a clean exit into a
    crash - losing preferences is an acceptable outcome there, a stack trace is
    not.
    """
    path = path or config_path()
    payload = {
        "version": CURRENT_VERSION,
        "target_fmt": settings.target_fmt,
        "mode": settings.mode,
        "extract_cover": settings.extract_cover,
        "strict_tables": settings.strict_tables,
        "include_subfolders": settings.include_subfolders,
        "keep_intermediates": settings.keep_intermediates,
        "dest_dir": str(settings.dest_dir) if settings.dest_dir else None,
        "geometry": settings.geometry,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-replace, so an interrupted save cannot leave a truncated
        # file that the next launch would silently discard as corrupt.
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return True
    except OSError:
        return False

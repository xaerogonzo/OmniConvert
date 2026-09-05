"""The control protocol between the conversion worker and the GUI.

The pipeline runs on a daemon thread and cannot touch Tk widgets, so it reports
progress by putting strings on a `queue.Queue` that the GUI drains on the main
thread. Most of those strings are ordinary log text; a few are *control
messages* that drive queue-row state.

Before v0.4.0 the wire format existed only as literals written in `pipeline.py`
and re-parsed by hand in `app.py`, which meant the protocol had no single
definition and could not be tested without a window.

Two rules keep it honest:

* `serialize` (via the helpers below) is the only place the syntax is written.
* `parse` is the only place it is read. No caller inspects a raw marker string.

`parse` is a trust boundary: it is fed every string the worker emits, so it
returns None for anything it does not recognise rather than raising. A malformed
message must degrade to "this is log text", never crash the GUI poll loop.

This module is deliberately Tk-free and dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Separates the index from a free-text payload: `__FILE_ERROR__2|boom`.
# Parsing splits on the FIRST separator only, so a payload may itself contain
# "|" or ":" - error messages routinely carry Windows paths and exception text.
_SEP = "|"


class Kind(StrEnum):
    """Every control message the worker can emit.

    The values are the literal wire prefixes; nothing outside this module should
    depend on them.
    """

    FILE_START = "__FILE_START__"        # batch: file <index> starting
    FILE_DONE = "__FILE_DONE__"          # batch: file <index> succeeded
    FILE_ERROR = "__FILE_ERROR__"        # batch: file <index> failed, <payload> = reason
    BATCH_DONE = "__BATCH_DONE__"        # batch finished normally
    BATCH_CANCELLED = "__BATCH_CANCELLED__"  # batch stopped early on the cancel Event
    DONE = "__DONE__"                    # legacy single-file success, <payload> = out path
    ERROR = "__ERROR__"                  # legacy single-file failure


#: Markers that carry an integer index of the file within the *submitted* list.
_INDEXED = (Kind.FILE_START, Kind.FILE_DONE, Kind.FILE_ERROR)

#: Markers that are the whole message, with nothing trailing.
_BARE = (Kind.BATCH_DONE, Kind.BATCH_CANCELLED, Kind.ERROR)


@dataclass(frozen=True)
class Marker:
    """A decoded control message.

    `index` is set only for the per-file markers; `payload` only for
    FILE_ERROR (the failure reason) and DONE (the output path).
    """

    kind: Kind
    index: int | None = None
    payload: str | None = None


# ---------------------------------------------------------------------------
# Serialisers - the only place the wire syntax is written
# ---------------------------------------------------------------------------

def file_start(index: int) -> str:
    return f"{Kind.FILE_START}{index}"


def file_done(index: int) -> str:
    return f"{Kind.FILE_DONE}{index}"


def file_error(index: int, message: str) -> str:
    """Encode a per-file failure and its reason.

    The separator is always emitted, so an empty reason round-trips as "" rather
    than becoming indistinguishable from a marker with no payload at all.

    Whitespace runs are collapsed to single spaces. The queue is line-oriented,
    so a multi-line traceback would otherwise be read back as several separate
    messages - and the reason is rendered on one queue row, where a traceback's
    indentation is noise.
    """
    flat = " ".join(str(message).split())
    return f"{Kind.FILE_ERROR}{index}{_SEP}{flat}"


def batch_done() -> str:
    return str(Kind.BATCH_DONE)


def batch_cancelled() -> str:
    return str(Kind.BATCH_CANCELLED)


def done(out_path) -> str:
    return f"{Kind.DONE}{out_path}"


def error() -> str:
    return str(Kind.ERROR)


# ---------------------------------------------------------------------------
# Parser - the only place the wire syntax is read
# ---------------------------------------------------------------------------

def _index(text: str) -> int | None:
    """Parse a marker index. Returns None for anything that is not a
    non-negative integer, so a corrupted message is treated as log text."""
    if not text.isdigit():          # rejects "", "-1", "1.0", "abc", " 1"
        return None
    return int(text)


def parse(msg: str) -> Marker | None:
    """Decode one queue message.

    Returns a Marker for a recognised control message, or None when `msg` is
    ordinary log text or is malformed. Never raises.
    """
    if not isinstance(msg, str) or not msg.startswith("__"):
        return None

    # Bare markers are exact matches, checked first so that (for example)
    # "__ERROR__" is never mistaken for a prefix of something longer.
    for kind in _BARE:
        if msg == kind:
            return Marker(kind)

    # Indexed markers: "__FILE_ERROR__2|reason", "__FILE_START__7".
    for kind in _INDEXED:
        if not msg.startswith(kind):
            continue
        rest = msg[len(kind):]
        if kind is Kind.FILE_ERROR:
            raw_index, sep, payload = rest.partition(_SEP)
            index = _index(raw_index)
            if index is None:
                return None
            return Marker(kind, index, payload if sep else None)
        index = _index(rest)
        return None if index is None else Marker(kind, index)

    # Legacy single-file success carries the output path as its payload.
    if msg.startswith(Kind.DONE):
        return Marker(Kind.DONE, payload=msg[len(Kind.DONE):] or None)

    return None

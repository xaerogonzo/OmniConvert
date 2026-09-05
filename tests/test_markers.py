"""The worker/GUI control protocol.

`parse()` is fed every string the conversion worker emits, so these tests care
at least as much about malformed input as about round-trips: a corrupted message
must degrade to "ordinary log text", never raise into the GUI poll loop.
"""

import pytest

from omniconvert.converters import markers
from omniconvert.converters.markers import Kind, Marker


class TestRoundTrip:
    @pytest.mark.parametrize(
        "encode, kind",
        [
            (markers.file_start, Kind.FILE_START),
            (markers.file_done, Kind.FILE_DONE),
        ],
    )
    @pytest.mark.parametrize("index", [0, 1, 7, 42, 1000])
    def test_indexed_markers(self, encode, kind, index):
        assert markers.parse(encode(index)) == Marker(kind, index)

    def test_bare_markers(self):
        assert markers.parse(markers.batch_done()) == Marker(Kind.BATCH_DONE)
        assert markers.parse(markers.batch_cancelled()) == Marker(Kind.BATCH_CANCELLED)
        assert markers.parse(markers.error()) == Marker(Kind.ERROR)

    def test_legacy_done_carries_the_output_path(self):
        m = markers.parse(markers.done(r"C:\Books\Draft (1).docx"))
        assert m.kind is Kind.DONE
        assert m.payload == r"C:\Books\Draft (1).docx"

    def test_file_error_carries_index_and_reason(self):
        m = markers.parse(markers.file_error(3, "boom"))
        assert m == Marker(Kind.FILE_ERROR, 3, "boom")


class TestErrorPayloads:
    """Real failure text is hostile: Windows paths, colons, and separators."""

    @pytest.mark.parametrize(
        "message",
        [
            "PermissionError: [Errno 13] C:\\Books\\x.pdf",   # colons and backslashes
            "a|b|c",                                          # the separator itself
            "weird: |: mixed |",
            "unicode ✗ → ✓",
            "x" * 4000,                                       # very long
        ],
    )
    def test_payload_survives_intact(self, message):
        m = markers.parse(markers.file_error(1, message))
        assert m.kind is Kind.FILE_ERROR and m.index == 1
        assert m.payload == message, "payload must split on the FIRST separator only"

    def test_empty_reason_round_trips_as_empty_not_none(self):
        m = markers.parse(markers.file_error(0, ""))
        assert m.payload == ""

    def test_multiline_reason_is_flattened(self):
        """The queue is line-oriented; a raw traceback would be read back as
        several separate messages."""
        encoded = markers.file_error(2, "Traceback:\n  line 1\n  line 2")
        assert "\n" not in encoded
        assert markers.parse(encoded).payload == "Traceback: line 1 line 2"


class TestMalformed:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "[*] Converting MD -> PDF via PyMuPDF...",
            "[✓] Done: Draft.docx",
            "[✗] Draft.pdf: boom",
            "just some text",
            "__NOT_A_MARKER__1",
            "__FILE_",
            "__",
        ],
    )
    def test_log_text_and_unknown_prefixes_are_not_markers(self, text):
        assert markers.parse(text) is None

    @pytest.mark.parametrize(
        "text",
        [
            "__FILE_START__",        # missing index
            "__FILE_START__abc",     # non-numeric
            "__FILE_START__-1",      # negative
            "__FILE_START__1.0",     # not an integer
            "__FILE_START__ 1",      # whitespace
            "__FILE_DONE__x",
            "__FILE_ERROR__|reason",  # missing index
            "__FILE_ERROR__abc|reason",
        ],
    )
    def test_bad_indices_yield_none_rather_than_raising(self, text):
        assert markers.parse(text) is None

    def test_file_error_without_a_separator_has_no_payload(self):
        assert markers.parse("__FILE_ERROR__4") == Marker(Kind.FILE_ERROR, 4, None)

    @pytest.mark.parametrize("value", [None, 123, b"__FILE_DONE__1", ["x"]])
    def test_non_strings_are_rejected(self, value):
        assert markers.parse(value) is None


class TestPrefixDisambiguation:
    """The marker names overlap as substrings; ordering in parse() matters."""

    def test_file_done_is_not_read_as_legacy_done(self):
        assert markers.parse("__FILE_DONE__0") == Marker(Kind.FILE_DONE, 0)

    def test_file_error_is_not_read_as_bare_error(self):
        assert markers.parse(markers.file_error(0, "x")).kind is Kind.FILE_ERROR

    def test_bare_error_is_not_read_as_file_error(self):
        assert markers.parse("__ERROR__") == Marker(Kind.ERROR)

    def test_bare_done_with_no_path_has_no_payload(self):
        assert markers.parse("__DONE__") == Marker(Kind.DONE, payload=None)


def test_module_is_tk_free():
    """The protocol must stay importable by the worker thread and by tests with
    no display."""
    import subprocess
    import sys

    probe = (
        "import sys; sys.path.insert(0, 'src');"
        "import omniconvert.converters.markers;"
        "print(any(m.startswith(('tkinter', 'customtkinter')) for m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert out.stdout.strip() == "False", out.stderr

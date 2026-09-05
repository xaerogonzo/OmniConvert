"""Batch orchestration: markers, continue-on-error, and cooperative cancel.

_run_single is monkeypatched throughout so these exercise run_batch's control
flow without doing real conversions.
"""

import threading

import pytest

from conftest import drain
from omniconvert.converters import markers, pipeline


@pytest.fixture
def sources(tmp_path):
    out = []
    for i in range(5):
        p = tmp_path / f"f{i}.md"
        p.write_text(f"# {i}\n", encoding="utf-8")
        out.append(p)
    return out


def _markers(msgs):
    """Control messages only, in order. The "__" test is the one piece of wire
    knowledge here; everything else goes through markers.parse()."""
    return [m for m in msgs if m.startswith("__")]


def _is(msg: str, kind: markers.Kind) -> bool:
    m = markers.parse(msg)
    return m is not None and m.kind is kind


def test_all_files_run_and_batch_done_is_posted(sources, log_q, monkeypatch):
    monkeypatch.setattr(pipeline, "_run_single", lambda p, q, claimed=None: p.src)
    pipeline.run_batch(sources, "md", "standard", False, log_q)
    ctrl = _markers(drain(log_q))
    assert ctrl.count(markers.file_done(0)) == 1
    assert sum(_is(m, markers.Kind.FILE_DONE) for m in ctrl) == 5
    assert ctrl[-1] == markers.batch_done()


def test_a_failure_does_not_stop_the_batch(sources, log_q, monkeypatch):
    def flaky(params, q, claimed=None):
        if params.src.name == "f2.md":
            raise RuntimeError("boom")
        return params.src

    monkeypatch.setattr(pipeline, "_run_single", flaky)
    pipeline.run_batch(sources, "md", "standard", False, log_q)
    msgs = drain(log_q)
    ctrl = _markers(msgs)
    errors = [markers.parse(m) for m in ctrl]
    errors = [e for e in errors if e and e.kind is markers.Kind.FILE_ERROR]
    assert [e.index for e in errors] == [2]
    assert errors[0].payload == "RuntimeError: boom", (
        "the failure reason must travel with the marker so the GUI can show it"
    )
    assert sum(_is(m, markers.Kind.FILE_DONE) for m in ctrl) == 4
    assert ctrl[-1] == markers.batch_done()
    assert any("4 succeeded, 1 failed" in m for m in msgs)


def test_cancel_before_the_first_file_converts_nothing(sources, log_q, monkeypatch):
    monkeypatch.setattr(pipeline, "_run_single", lambda p, q, claimed=None: p.src)
    cancel = threading.Event()
    cancel.set()
    pipeline.run_batch(sources, "md", "standard", False, log_q, cancel=cancel)
    ctrl = _markers(drain(log_q))
    assert ctrl == [markers.batch_cancelled()]


def test_cancel_mid_batch_stops_at_the_next_boundary(sources, log_q, monkeypatch):
    """Cancellation is between files: the in-flight file still finishes."""
    cancel = threading.Event()
    seen = []

    def worker(params, q, claimed=None):
        seen.append(params.src.name)
        if len(seen) == 2:
            cancel.set()          # user hits Cancel while file 2 is converting
        return params.src

    monkeypatch.setattr(pipeline, "_run_single", worker)
    pipeline.run_batch(sources, "md", "standard", False, log_q, cancel=cancel)

    msgs = drain(log_q)
    assert seen == ["f0.md", "f1.md"], "the in-flight file must still complete"
    assert _markers(msgs)[-1] == markers.batch_cancelled()
    assert markers.batch_done() not in msgs
    assert any("2 converted" in m and "3 not started" in m for m in msgs)


def test_no_cancel_event_behaves_exactly_as_before(sources, log_q, monkeypatch):
    monkeypatch.setattr(pipeline, "_run_single", lambda p, q, claimed=None: p.src)
    pipeline.run_batch(sources, "md", "standard", False, log_q, cancel=None)
    assert _markers(drain(log_q))[-1] == markers.batch_done()


def test_strict_tables_reaches_convert_params(sources, log_q, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "_run_single",
                        lambda p, q, claimed=None: seen.append(p.strict_tables) or p.src)
    pipeline.run_batch(sources[:1], "pdf", "standard", False, log_q,
                       strict_tables=False)
    assert seen == [False]


def test_start_batch_returns_a_live_daemon_thread(sources, log_q, monkeypatch):
    monkeypatch.setattr(pipeline, "_run_single", lambda p, q, claimed=None: p.src)
    t = pipeline.start_batch(sources, "md", "standard", False, log_q)
    assert t.daemon
    t.join(timeout=5)
    assert not t.is_alive()
    assert markers.batch_done() in drain(log_q)


def test_hifi_docx_to_pdf_falls_back_to_the_standard_path(tmp_path, log_q,
                                                          monkeypatch):
    """When MS Word is unavailable the pipeline must still produce a PDF.

    Before v0.3.0 this fell back to weasyprint; it now falls back to the
    PyMuPDF renderer. The fallback is easy to break because the exception
    handler sits mid-function and falls *through* rather than returning.
    """
    pytest.importorskip("pymupdf")
    docx_mod = pytest.importorskip("docx")

    src = tmp_path / "Fallback.docx"
    d = docx_mod.Document()
    d.add_heading("Fallback Heading", level=1)
    d.add_paragraph("body text")
    d.save(str(src))

    def no_word(*a, **k):
        raise OSError("Word not installed")

    monkeypatch.setattr(pipeline.hifi, "docx_to_pdf", no_word)

    out = pipeline._run_single(
        pipeline.ConvertParams(src=src, target_fmt="pdf", mode="hifi",
                               extract_cover=False, strict_tables=True),
        log_q,
    )
    assert out.exists() and out.stat().st_size > 0

    import pymupdf
    with pymupdf.open(str(out)) as doc:
        assert "Fallback Heading" in doc[0].get_text()

    msgs = drain(log_q)
    assert any("MS Word path unavailable" in m and "Word not installed" in m
               for m in msgs), "the real error message must reach the log"

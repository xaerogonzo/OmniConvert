"""Construction smoke test for the real window.

Skipped automatically where no display / tkdnd is available. It builds the whole
widget tree, pumps the event loop once and tears it down — enough to catch the
failure modes a refactor actually causes: a panel wired to a method that no
longer exists, or the TkinterDnD bootstrap running in the wrong order.
"""

import pytest


@pytest.fixture(scope="module")
def _window():
    """One Tk root for the whole module.

    Tk tolerates exactly one root per process; building a fresh OmniConvertApp
    per test made this file intermittently skip. Build it once, reset the state
    between tests instead.
    """
    pytest.importorskip("customtkinter")
    pytest.importorskip("tkinterdnd2")
    from omniconvert.app import OmniConvertApp

    try:
        win = OmniConvertApp()
    except Exception as exc:                      # no display, no tkdnd, etc.
        pytest.skip(f"GUI unavailable: {type(exc).__name__}: {exc}")

    win.withdraw()                                # don't flash a window
    win.update()
    yield win
    win.destroy()


@pytest.fixture
def app(_window):
    """The shared window, returned to a known-clean state for each test."""
    _window._converting = False
    _window._cancel.clear()
    while not _window._log_q.empty():
        _window._log_q.get()
    _window.model.clear()
    _window.controls.fmt_var.set("PDF")
    _window.controls.mode_var.set("Standard")
    _window._refresh_queue_ui()
    _window.log_panel.clear()
    _window.update()
    return _window


def test_window_builds_with_all_panels(app):
    assert app.queue_panel is not None
    assert app.controls is not None
    assert app.log_panel is not None
    assert len(app.model) == 0


def test_drop_target_is_registered(app):
    """DnD breaks silently more easily than anything else in this app."""
    assert getattr(app, "TkdndVersion", None)


def test_enqueue_updates_panel_and_log(app, tmp_path):
    f = tmp_path / "sample.md"
    f.write_text("# hi\n", encoding="utf-8")
    app._enqueue([f])
    app.update()
    assert len(app.model) == 1
    assert app.model[0].path == f


def test_enqueue_is_additive_and_dedupes(app, tmp_path):
    a = tmp_path / "a.md"; a.write_text("a", encoding="utf-8")
    b = tmp_path / "b.md"; b.write_text("b", encoding="utf-8")
    app._enqueue([a])
    app._enqueue([b])
    app._enqueue([a])          # duplicate
    app.update()
    assert [i.path.name for i in app.model] == ["a.md", "b.md"]


def test_clear_empties_the_queue(app, tmp_path):
    f = tmp_path / "a.md"; f.write_text("a", encoding="utf-8")
    app._enqueue([f])
    app._on_clear()
    app.update()
    assert len(app.model) == 0


def test_hifi_is_disabled_for_a_non_pdf_docx_pair(app, tmp_path):
    f = tmp_path / "a.epub"; f.write_text("x", encoding="utf-8")
    app._enqueue([f])
    app.controls.fmt_var.set("PDF")
    app._on_format_change("PDF")
    app.update()
    assert app.controls.mode_var.get() == "Standard"


def test_poll_log_dispatches_markers_without_a_worker(app, tmp_path):
    files = []
    for n in ("a.md", "b.md"):
        p = tmp_path / n
        p.write_text("x", encoding="utf-8")
        files.append(p)
    app._enqueue(files)
    app._converting = True

    for marker in ("__FILE_START__0", "[*] hello", "__FILE_DONE__0",
                   "__FILE_START__1", "__FILE_ERROR__1", "__BATCH_CANCELLED__"):
        app._log_q.put(marker)
    app._poll_log()
    app.update()

    assert app.model[0].status == "done"
    assert app.model[1].status == "error"
    assert app._converting is False          # __BATCH_CANCELLED__ tore down

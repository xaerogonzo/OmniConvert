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
    # Every piece of window state a test can mutate has to be reset here, or it
    # leaks into the next test through the shared root.
    _window._dest_dir = None
    _window._refresh_dest_label()
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
    # Markers index the SUBMITTED list, so a run's mapping has to exist for them
    # to land anywhere. A full run submits every row in order.
    app._batch_indices = list(range(len(app.model)))
    app._batch_sources = app.model.paths

    from omniconvert.converters import markers

    for msg in (
        markers.file_start(0),
        "[*] hello",                     # ordinary log text
        markers.file_done(0),
        markers.file_start(1),
        markers.file_error(1, "RuntimeError: boom"),
        "__FILE_DONE__not_a_number",     # malformed: must not crash the poll loop
        "__NOT_A_MARKER__9",             # unknown prefix: treated as log text
        markers.batch_cancelled(),
    ):
        app._log_q.put(msg)
    app._poll_log()
    app.update()

    assert app.model[0].status == "done"
    assert app.model[1].status == "error"
    assert app._converting is False       # the cancelled marker tore the run down


class TestOutputDestination:
    """One resolver, and every consumer derives from it."""

    def test_default_is_no_destination(self, app):
        assert app._effective_dest_dir() is None

    def test_a_chosen_folder_becomes_effective(self, app, tmp_path):
        app._dest_dir = tmp_path
        assert app._effective_dest_dir() == tmp_path

    def test_a_vanished_folder_falls_back(self, app, tmp_path):
        """Removable drives and network shares disappear; the app must not."""
        gone = tmp_path / "unplugged"
        app._dest_dir = gone
        assert app._effective_dest_dir() is None

    def test_cover_preview_follows_the_destination(self, app, tmp_path):
        from omniconvert.app import cover_path_for

        src = tmp_path / "src" / "Book.pdf"
        src.parent.mkdir()
        src.write_bytes(b"x")
        dest = tmp_path / "out"
        dest.mkdir()

        app._enqueue([src])
        assert cover_path_for(src, None).parent == src.parent
        app._dest_dir = dest
        assert cover_path_for(src, app._effective_dest_dir()).parent == dest

    def test_open_folder_prefers_the_destination(self, app, tmp_path, monkeypatch):
        """It used to open source.parent unconditionally, which stops being the
        output folder the moment a destination is set."""
        opened = []
        monkeypatch.setattr(app, "_reveal", opened.append)

        src = tmp_path / "src" / "Book.md"
        src.parent.mkdir()
        src.write_text("x", encoding="utf-8")
        app._enqueue([src])

        app._open_output_folder()
        assert opened == [src.parent]

        dest = tmp_path / "out"
        dest.mkdir()
        app._dest_dir = dest
        app._open_output_folder()
        assert opened[-1] == dest

    def test_destination_change_is_refused_mid_batch(self, app, tmp_path):
        app._converting = True
        try:
            app._on_clear_output()
        finally:
            app._converting = False
        # Rejected, so the destination is untouched.
        assert app._dest_dir is None


class TestQueueControl:
    """Per-row remove, failure reasons, and retry's submitted->model mapping."""

    def _queue(self, app, tmp_path, n=4):
        paths = []
        for i in range(n):
            p = tmp_path / f"f{i}.md"
            p.write_text(f"# {i}\n", encoding="utf-8")
            paths.append(p)
        app._enqueue(paths)
        return paths

    def test_remove_drops_the_row_and_keeps_the_rest_aligned(self, app, tmp_path):
        paths = self._queue(app, tmp_path)
        app._on_row_remove(1)
        app.update()
        assert [i.path.name for i in app.model] == ["f0.md", "f2.md", "f3.md"]

    def test_remove_is_refused_mid_batch(self, app, tmp_path):
        """Removing would shift indices under a worker already reporting by
        position, marking the wrong rows done."""
        self._queue(app, tmp_path)
        app._converting = True
        try:
            app._on_row_remove(1)
        finally:
            app._converting = False
        assert len(app.model) == 4

    def test_a_failure_reason_reaches_the_row(self, app, tmp_path):
        from omniconvert.converters import markers

        self._queue(app, tmp_path)
        app._converting = True
        app._batch_indices = list(range(len(app.model)))
        app._log_q.put(markers.file_error(2, "PermissionError: denied"))
        app._log_q.put(markers.batch_done())
        app._poll_log()
        app.update()

        assert app.model[2].status == "error"
        assert app.model[2].error == "PermissionError: denied"

    def test_retry_submits_only_failures_and_maps_markers_back(self, app, tmp_path,
                                                               monkeypatch):
        """The heart of retry: submitted position 0 must mean model row 1."""
        from omniconvert.converters import markers

        self._queue(app, tmp_path)
        app.model.set_status(0, "done")
        app.model.set_status(1, "error", "boom")
        app.model.set_status(2, "done")
        app.model.set_status(3, "error", "boom")

        submitted = {}
        monkeypatch.setattr(
            "omniconvert.converters.pipeline.start_batch",
            lambda **kw: submitted.update(kw) or None,
        )
        app._on_retry_failed()
        app.update()

        assert [p.name for p in submitted["sources"]] == ["f1.md", "f3.md"]
        assert app._batch_indices == [1, 3]

        # Submitted item 0 is model row 1.
        app._log_q.put(markers.file_done(0))
        app._poll_log()
        app.update()
        assert app.model[1].status == "done"
        assert app.model[0].status == "done", "untouched success must survive"
        assert app.model[3].status == "pending", "the other failure is still queued"

    def test_retry_keeps_successful_rows(self, app, tmp_path, monkeypatch):
        self._queue(app, tmp_path)
        app.model.set_status(0, "done")
        app.model.set_status(1, "error", "boom")
        monkeypatch.setattr("omniconvert.converters.pipeline.start_batch",
                            lambda **kw: None)
        app._on_retry_failed()
        app.update()
        assert app.model[0].status == "done"

    def test_retry_is_a_no_op_without_failures(self, app, tmp_path, monkeypatch):
        self._queue(app, tmp_path)
        called = []
        monkeypatch.setattr("omniconvert.converters.pipeline.start_batch",
                            lambda **kw: called.append(kw))
        app._on_retry_failed()
        assert called == []

    def test_stale_markers_are_ignored(self, app, tmp_path):
        """A marker indexing beyond this run's submission must not touch a row."""
        from omniconvert.converters import markers

        self._queue(app, tmp_path)
        app._converting = True
        app._batch_indices = [0]          # a one-file run
        app._log_q.put(markers.file_done(7))
        app._log_q.put(markers.batch_done())
        app._poll_log()
        app.update()
        assert all(i.status == "pending" for i in app.model)


class TestSettingsIntegration:
    def test_round_trip_through_the_window(self, app, tmp_path):
        """What the user set is what comes back."""
        from omniconvert import settings

        dest = tmp_path / "out"
        dest.mkdir()
        app.controls.fmt_var.set("EPUB")
        app.controls.set_preferred_mode("High-Fidelity")
        app.controls.set_options(extract_cover=False, strict_tables=False,
                                 include_subfolders=True, keep_intermediates=False)
        app._dest_dir = dest
        app.update()

        cfg = tmp_path / "settings.json"
        assert settings.save(app._current_settings(), cfg)
        loaded = settings.load(cfg)

        assert loaded.target_fmt == "EPUB"
        assert loaded.mode == "High-Fidelity"
        assert loaded.extract_cover is False
        assert loaded.strict_tables is False
        assert loaded.include_subfolders is True
        assert loaded.keep_intermediates is False
        assert loaded.dest_dir == dest

    def test_mode_preference_survives_being_forced_to_standard(self, app, tmp_path):
        """An empty queue disables High-Fidelity, which used to overwrite the
        saved preference with 'Standard' on every launch."""
        app.controls.set_preferred_mode("High-Fidelity")
        app._on_format_change("PDF")          # empty queue -> hifi unavailable
        app.update()

        assert app.controls.mode_var.get() == "Standard", "live mode is forced"
        assert app._current_settings().mode == "High-Fidelity", (
            "but the user's preference is what gets persisted"
        )

    def test_preference_is_reapplied_when_the_pair_allows_it(self, app, tmp_path):
        src = tmp_path / "Book.pdf"
        src.write_bytes(b"x")
        app.controls.set_preferred_mode("High-Fidelity")
        app._enqueue([src])
        app.controls.fmt_var.set("DOCX")
        app._on_format_change("DOCX")         # PDF -> DOCX is a hifi pair
        app.update()
        assert app.controls.mode_var.get() == "High-Fidelity"

    def test_applying_settings_does_not_restore_a_vanished_destination(self, app,
                                                                       tmp_path):
        from omniconvert import settings

        app._settings = settings.Settings(dest_dir=tmp_path / "unplugged")
        app._apply_settings()
        app.update()
        assert app._dest_dir is None

    def test_a_bad_saved_geometry_does_not_break_the_window(self, app):
        """A corrupt string must never reach Tk unguarded."""
        app._apply_geometry("not-a-geometry")
        app.update()
        assert app.winfo_exists()

    def test_settings_never_carry_queue_state(self, app, tmp_path):
        """'Remember my preferences' must not become 'restore my previous job'."""
        f = tmp_path / "a.md"
        f.write_text("x", encoding="utf-8")
        app._enqueue([f])
        app.model.set_status(0, "error", "boom")

        saved = app._current_settings()
        fields = vars(saved)
        for forbidden in ("queue", "items", "sources", "status", "error",
                          "selected", "running"):
            assert not any(forbidden in k for k in fields), fields

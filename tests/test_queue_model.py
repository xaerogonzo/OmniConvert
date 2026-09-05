"""Queue state rules, exercised without a display.

Extracting this out of OmniConvertApp is what makes these testable at all — in
v0.2 every one of these rules lived inside the Tk widget class.
"""

from pathlib import Path

import pytest

from omniconvert.ui.queue_model import QueueModel


@pytest.fixture
def files(tmp_path):
    out = []
    for name in ("a.pdf", "b.docx", "c.epub"):
        p = tmp_path / name
        p.write_text("x", encoding="utf-8")
        out.append(p)
    return out


class TestAdd:
    def test_appends_rather_than_replacing(self, files):
        m = QueueModel()
        assert m.add(files[:2]) == 2
        assert m.add(files[2:]) == 1
        assert m.paths == files

    def test_duplicates_are_skipped(self, files):
        m = QueueModel()
        m.add(files)
        assert m.add(files) == 0
        assert len(m) == 3

    def test_dedup_survives_a_relative_path(self, files, monkeypatch):
        m = QueueModel()
        m.add([files[0]])
        monkeypatch.chdir(files[0].parent)
        assert m.add([Path(files[0].name)]) == 0

    def test_dedup_is_case_insensitive(self, files):
        m = QueueModel()
        m.add([files[0]])
        assert m.add([Path(str(files[0]).upper())]) == 0

    def test_new_items_start_pending(self, files):
        m = QueueModel()
        m.add(files)
        assert [i.status for i in m] == ["pending"] * 3


class TestRemoveAndClear:
    def test_clear_resets_everything(self, files):
        m = QueueModel()
        m.add(files)
        m.selected_idx, m.running_idx = 1, 2
        m.clear()
        assert len(m) == 0 and m.selected_idx == -1 and m.running_idx == -1

    def test_remove_shifts_cursors_above_it_down(self, files):
        m = QueueModel()
        m.add(files)
        m.selected_idx, m.running_idx = 2, 2
        m.remove(0)
        assert m.paths == files[1:]
        assert m.selected_idx == 1 and m.running_idx == 1

    def test_removing_the_cursor_row_clears_it(self, files):
        m = QueueModel()
        m.add(files)
        m.selected_idx = 1
        m.remove(1)
        assert m.selected_idx == -1

    def test_out_of_range_remove_is_a_no_op(self, files):
        m = QueueModel()
        m.add(files)
        m.remove(99)
        assert len(m) == 3


class TestStatus:
    def test_set_running_updates_status_and_cursor(self, files):
        m = QueueModel()
        m.add(files)
        m.set_running(1)
        assert m[1].status == "running" and m.running_idx == 1

    def test_reset_statuses_clears_rows_and_cursors(self, files):
        m = QueueModel()
        m.add(files)
        m.set_running(0)
        m.set_status(0, "done")
        m.selected_idx = 2
        m.reset_statuses()
        assert [i.status for i in m] == ["pending"] * 3
        assert m.selected_idx == -1 and m.running_idx == -1

    def test_out_of_range_status_is_a_no_op(self, files):
        m = QueueModel()
        m.add(files)
        m.set_status(99, "done")
        assert [i.status for i in m] == ["pending"] * 3


class TestSelection:
    def test_clicking_a_row_pins_it(self, files):
        m = QueueModel()
        m.add(files)
        m.set_running(0)
        m.select(2, converting=True)
        assert m.selected_idx == 2 and not m.is_auto_tracking

    def test_clicking_the_running_row_rearms_auto_tracking(self, files):
        """The v0.2 rule: re-clicking the active row un-pins the preview."""
        m = QueueModel()
        m.add(files)
        m.set_running(1)
        m.select(2, converting=True)
        m.select(1, converting=True)
        assert m.selected_idx == -1 and m.is_auto_tracking

    def test_clicking_that_row_while_idle_just_pins_it(self, files):
        m = QueueModel()
        m.add(files)
        m.running_idx = 1
        m.select(1, converting=False)
        assert m.selected_idx == 1

    def test_preview_follows_the_runner_when_auto_tracking(self, files):
        m = QueueModel()
        m.add(files)
        m.set_running(2)
        assert m.preview_idx == 2

    def test_preview_honours_the_pin(self, files):
        m = QueueModel()
        m.add(files)
        m.set_running(2)
        m.select(0, converting=True)
        assert m.preview_idx == 0

    def test_preview_falls_back_to_the_first_row_when_idle(self, files):
        m = QueueModel()
        m.add(files)
        assert m.preview_idx == 0

    def test_preview_is_minus_one_when_empty(self):
        assert QueueModel().preview_idx == -1


class TestErrorState:
    def test_a_failure_records_its_reason(self, files):
        m = QueueModel()
        m.add(files)
        m.set_status(1, "error", "RuntimeError: boom")
        assert m[1].status == "error" and m[1].error == "RuntimeError: boom"

    def test_success_clears_a_previous_reason(self, files):
        """A retry that works must stop showing why it failed last time."""
        m = QueueModel()
        m.add(files)
        m.set_status(1, "error", "boom")
        m.set_status(1, "done")
        assert m[1].error is None

    def test_reset_statuses_clears_errors(self, files):
        """A fresh batch showing last run's failures would be misleading."""
        m = QueueModel()
        m.add(files)
        m.set_status(0, "error", "boom")
        m.set_status(2, "done")
        m.reset_statuses()
        assert [i.status for i in m] == ["pending"] * 3
        assert all(i.error is None for i in m)

    def test_failed_indices_lists_only_failures(self, files):
        m = QueueModel()
        m.add(files)
        m.set_status(0, "done")
        m.set_status(1, "error", "boom")
        assert m.failed_indices == [1]
        assert m.has_failures

    def test_pending_rows_are_not_failures(self, files):
        """Cancellation leaves unstarted files pending, so retry skips them."""
        m = QueueModel()
        m.add(files)
        m.set_status(0, "done")
        assert m.failed_indices == [] and not m.has_failures


class TestResetItems:
    def test_resets_only_the_named_rows(self, files):
        m = QueueModel()
        m.add(files)
        m.set_status(0, "done")
        m.set_status(1, "error", "boom")
        m.set_status(2, "done")

        m.reset_items(m.failed_indices)

        assert [i.status for i in m] == ["done", "pending", "done"], (
            "retry must not discard completion state the user already earned"
        )
        assert m[1].error is None

    def test_out_of_range_indices_are_ignored(self, files):
        m = QueueModel()
        m.add(files)
        m.set_status(0, "done")
        m.reset_items([99, -5])
        assert m[0].status == "done"

    def test_clears_the_running_cursor(self, files):
        m = QueueModel()
        m.add(files)
        m.set_running(2)
        m.reset_items([2])
        assert m.running_idx == -1

    def test_repeated_retry_of_a_persistent_failure(self, files):
        """The same file can keep failing and keep being retried."""
        m = QueueModel()
        m.add(files)
        for _ in range(3):
            m.set_status(1, "error", "still broken")
            assert m.has_failures
            m.reset_items(m.failed_indices)
            assert m[1].status == "pending"

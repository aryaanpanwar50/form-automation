import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from form_automation import desktop
from form_automation.desktop import MainWindow


class DesktopStatusTests(unittest.TestCase):
    @staticmethod
    def _runtime_status(*, state="error", code="form_error", updated_at="2026-10-23T12:00:00"):
        return {
            "state": state,
            "code": code,
            "message": "A current runtime message.",
            "updated_at": updated_at,
        }

    def test_unchanged_runtime_status_preserves_current_feedback(self) -> None:
        runtime_status = self._runtime_status()
        window = SimpleNamespace(
            settings_store=Mock(),
            _last_notified_status=("error", "form_error", "2026-10-23T12:00:00"),
            _refresh_session_status=Mock(),
            ready_status=Mock(),
            tray_icon=None,
        )
        window.settings_store.get_settings.return_value = {
            "automation_status": runtime_status
        }

        MainWindow._refresh_runtime_status(window)

        window.ready_status.setText.assert_not_called()

    def test_changed_runtime_status_replaces_previous_feedback(self) -> None:
        runtime_status = self._runtime_status(state="succeeded", code="submitted")
        window = SimpleNamespace(
            settings_store=Mock(),
            _last_notified_status=None,
            _refresh_session_status=Mock(),
            ready_status=Mock(),
            tray_icon=None,
        )
        window.settings_store.get_settings.return_value = {
            "automation_status": runtime_status
        }

        MainWindow._refresh_runtime_status(window)

        window.ready_status.setText.assert_called_once_with("A current runtime message.")

    def test_status_bar_refresh_does_not_replace_current_feedback(self) -> None:
        runtime_status = self._runtime_status()
        window = SimpleNamespace(
            active_checkbox=Mock(),
            settings_store=Mock(),
            automation_status=Mock(),
            ready_status=Mock(),
            session_status=Mock(),
            retry_button=Mock(),
            _has_valid_session=lambda: True,
        )
        window.active_checkbox.isChecked.return_value = True
        window.settings_store.get_settings.return_value = {
            "automation_status": runtime_status,
            "pending_task": None,
        }

        MainWindow._refresh_status_bar(window)

        window.ready_status.setText.assert_not_called()

    def test_save_all_does_not_replace_validation_feedback_with_ready(self) -> None:
        window = SimpleNamespace(
            response_save_timer=Mock(),
            _save_form_responses=Mock(),
            _save_settings=Mock(),
            ready_status=Mock(),
        )

        MainWindow._save_all(window)

        window.ready_status.setText.assert_not_called()

    def test_settings_save_restores_a_persistent_runtime_error(self) -> None:
        runtime_status = self._runtime_status()
        window = MainWindow.__new__(MainWindow)
        window.settings_store = Mock()
        window.settings_store.get_settings.return_value = {
            "automation_status": runtime_status
        }
        window.ready_status = Mock()
        window._refresh_status_bar = Mock()

        def save_with_ordinary_feedback(_window) -> None:
            window.ready_status.setText("Settings saved.")

        with patch.object(
            desktop._MainWindowBehavior,
            "_save_settings",
            autospec=True,
            side_effect=save_with_ordinary_feedback,
        ):
            MainWindow._save_settings(window)

        self.assertEqual(
            window.ready_status.setText.call_args_list[-1].args,
            ("A current runtime message.",),
        )

    def test_enabling_automation_registers_startup_at_sign_in(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.work_day_combo = Mock()
        window.work_day_combo.currentData.return_value = 2
        window.active_checkbox = Mock()
        window.active_checkbox.isChecked.return_value = True
        window.schedule_time = Mock()
        window.schedule_time.time.return_value = SimpleNamespace(
            hour=lambda: 9, minute=lambda: 30
        )
        window.settings_store = Mock()
        window.ready_status = Mock()
        window._has_valid_session = lambda: True
        window._restore_persistent_runtime_error = Mock()
        window._refresh_status_bar = Mock()

        with (
            patch.object(desktop, "sync_schedule"),
            patch.object(desktop, "apply_startup_preference") as apply_preference,
        ):
            MainWindow._save_settings(window)

        apply_preference.assert_called_once_with(True)

    def test_failed_enable_reports_that_startup_could_not_be_added(self) -> None:
        window = self._settings_save_window(automation_active=True)

        with (
            patch.object(desktop, "sync_schedule"),
            patch.object(desktop, "apply_startup_preference", side_effect=OSError),
        ):
            desktop._MainWindowBehavior._save_settings(window)

        self.assertEqual(
            window.ready_status.setText.call_args.args,
            (
                "Automation is active, but Form Automation could not be set to start "
                "when you sign in.",
            ),
        )

    def test_failed_disable_warns_that_startup_may_remain_enabled(self) -> None:
        window = self._settings_save_window(automation_active=False)

        with (
            patch.object(desktop, "sync_schedule"),
            patch.object(desktop, "apply_startup_preference", side_effect=OSError),
        ):
            desktop._MainWindowBehavior._save_settings(window)

        self.assertEqual(
            window.ready_status.setText.call_args.args,
            (
                "Automation is paused, but the start-at-sign-in setting could not be "
                "removed. Form Automation may still start when you sign in.",
            ),
        )

    def test_startup_failure_is_shown_with_a_persistent_runtime_error(self) -> None:
        window = MainWindow.__new__(MainWindow)
        window.work_day_combo = Mock()
        window.work_day_combo.currentData.return_value = 2
        window.active_checkbox = Mock()
        window.active_checkbox.isChecked.return_value = True
        window.schedule_time = Mock()
        window.schedule_time.time.return_value = SimpleNamespace(
            hour=lambda: 9, minute=lambda: 30
        )
        window.settings_store = Mock()
        window.settings_store.get_settings.return_value = {
            "automation_status": self._runtime_status()
        }
        window.ready_status = Mock()
        window._has_valid_session = lambda: True
        window._refresh_status_bar = Mock()

        with (
            patch.object(desktop, "sync_schedule"),
            patch.object(desktop, "apply_startup_preference", side_effect=OSError),
        ):
            MainWindow._save_settings(window)

        message = window.ready_status.setText.call_args.args[0]
        self.assertIn("A current runtime message.", message)
        self.assertIn("could not be set to start when you sign in", message)

    @staticmethod
    def _settings_save_window(*, automation_active: bool) -> SimpleNamespace:
        active_checkbox = Mock()
        active_checkbox.isChecked.return_value = automation_active
        return SimpleNamespace(
            work_day_combo=Mock(currentData=Mock(return_value=2)),
            active_checkbox=active_checkbox,
            schedule_time=Mock(
                time=Mock(return_value=SimpleNamespace(hour=lambda: 9, minute=lambda: 30))
            ),
            settings_store=Mock(),
            ready_status=Mock(),
            _has_valid_session=lambda: True,
        )


if __name__ == "__main__":
    unittest.main()

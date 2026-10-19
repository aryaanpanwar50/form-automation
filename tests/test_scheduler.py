import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

from form_automation.local_settings import LocalSettingsStore
from form_automation.scheduler import (
    pending_task_is_due_today,
    refresh_pending_task_work_day,
    run_automation,
    work_day_for_date,
)
from form_automation.scripts.automation import FormUnavailableError, SessionExpiredError


class SchedulerStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = LocalSettingsStore(Path(self.temp_dir.name) / "settings.json")
        self.store.update_automation_settings(work_day=2, automation_active=True)
        self.store.update_schedule_time("00:00")
        self.store.set_pending_task(date.today(), 2)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_with_submission(self, side_effect) -> None:
        with (
            patch("form_automation.scheduler.get_settings_store", return_value=self.store),
            patch("form_automation.scheduler.has_local_auth_profile", return_value=True),
            patch("form_automation.scripts.automation.submit_form", side_effect=side_effect),
        ):
            run_automation()

    def test_expired_session_keeps_task_and_records_reconnect_error(self) -> None:
        self.run_with_submission(SessionExpiredError("Reconnect Google account."))

        settings = self.store.get_settings()
        self.assertEqual(settings["pending_task"]["scheduled_date"], date.today().isoformat())
        self.assertEqual(settings["automation_status"]["code"], "session_expired")
        self.assertEqual(settings["automation_status"]["state"], "error")

    def test_manual_retry_runs_after_a_previous_session_expiry(self) -> None:
        self.store.set_automation_status(
            "error", "session_expired", "Reconnect Google account."
        )
        with (
            patch("form_automation.scheduler.get_settings_store", return_value=self.store),
            patch("form_automation.scheduler.has_local_auth_profile", return_value=True),
            patch("form_automation.scripts.automation.submit_form") as submit_form,
        ):
            run_automation(retry=True)

        submit_form.assert_called_once()

    def test_submission_receives_the_configured_reconnect_email(self) -> None:
        self.store.update_google_account_email("student@example.com")
        with (
            patch("form_automation.scheduler.get_settings_store", return_value=self.store),
            patch("form_automation.scheduler.has_local_auth_profile", return_value=True),
            patch("form_automation.scripts.automation.submit_form") as submit_form,
        ):
            run_automation()

        self.assertEqual(
            submit_form.call_args.kwargs["account_email"], "student@example.com"
        )

    def test_missing_profile_keeps_task_and_requests_connection(self) -> None:
        with (
            patch("form_automation.scheduler.get_settings_store", return_value=self.store),
            patch("form_automation.scheduler.has_local_auth_profile", return_value=False),
        ):
            run_automation()

        settings = self.store.get_settings()
        self.assertIsNotNone(settings["pending_task"])
        self.assertEqual(settings["automation_status"]["code"], "session_required")

    def test_form_error_keeps_task_and_records_message(self) -> None:
        self.run_with_submission(FormUnavailableError("Key tasks question was not found."))

        settings = self.store.get_settings()
        self.assertIsNotNone(settings["pending_task"])
        self.assertEqual(settings["automation_status"]["code"], "form_error")
        self.assertIn("Key tasks", settings["automation_status"]["message"])

    def test_success_completes_task_and_records_success(self) -> None:
        self.run_with_submission(None)

        settings = self.store.get_settings()
        self.assertNotEqual(settings["pending_task"]["scheduled_date"], date.today().isoformat())
        self.assertEqual(settings["automation_status"]["code"], "submitted")
        self.assertEqual(settings["automation_status"]["state"], "succeeded")

    def test_a_changed_time_runs_even_when_the_queue_is_already_tomorrow(self) -> None:
        self.store.set_pending_task(date.today() + timedelta(days=1), 2)

        self.run_with_submission(None)

        settings = self.store.get_settings()
        self.assertEqual(settings["automation_status"]["code"], "submitted")


class MissedTaskSchedulingTests(unittest.TestCase):
    def test_calendar_override_takes_priority_over_the_app_default(self) -> None:
        selected_date = date(2026, 10, 21)
        settings = {"work_day": 2, "calendar_work_days": {"2026-10-21": 1}}

        self.assertEqual(work_day_for_date(settings, selected_date), 1)
        self.assertEqual(work_day_for_date(settings, date(2026, 10, 22)), 2)

    def test_calendar_override_updates_the_queued_task(self) -> None:
        selected_date = date.today() + timedelta(days=1)
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = LocalSettingsStore(Path(temporary_directory) / "settings.json")
            store.update_automation_settings(work_day=2, automation_active=True)
            store.set_pending_task(selected_date, 2)
            store.set_calendar_work_day(selected_date, 1)

            refresh_pending_task_work_day(store, store.get_settings())

            self.assertEqual(store.get_settings()["pending_task"]["work_day"], 1)
    def test_todays_pending_task_is_due_after_its_scheduled_time(self) -> None:
        now = datetime.combine(date.today(), time(15, 30))

        self.assertTrue(
            pending_task_is_due_today(
                {"scheduled_date": date.today().isoformat(), "work_day": 2},
                "15:00",
                now,
            )
        )

    def test_todays_pending_task_is_not_due_before_its_scheduled_time(self) -> None:
        now = datetime.combine(date.today(), time(15, 0))

        self.assertFalse(
            pending_task_is_due_today(
                {"scheduled_date": date.today().isoformat(), "work_day": 2},
                "15:30",
                now,
            )
        )

    def test_a_task_from_another_date_is_not_caught_up(self) -> None:
        now = datetime.combine(date.today(), time(15, 30))

        self.assertFalse(
            pending_task_is_due_today(
                {"scheduled_date": "2020-01-01", "work_day": 2},
                "15:00",
                now,
            )
        )


if __name__ == "__main__":
    unittest.main()

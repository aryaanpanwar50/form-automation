import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from form_automation.local_settings import LocalSettingsStore


class LocalSettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp_dir.name) / "settings.json"
        self.store = LocalSettingsStore(self.settings_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_defaults_are_local_and_inactive(self) -> None:
        self.assertEqual(
            self.store.get_settings(),
            {
                "work_day": None,
                "automation_active": False,
                "start_at_login": False,
                "schedule_time": None,
                "pending_task": None,
                "automation_status": None,
                "calendar_work_days": {},
                "google_account_email": "",
                "form_responses": {
                    "key_tasks": "Did today's assigned task",
                    "challenges": "None",
                    "challenge_resolution": "None",
                    "tomorrow_plan": "do tomorrows assigned task",
                },
            },
        )

    def test_start_at_login_is_disabled_by_default_and_can_be_saved(self) -> None:
        self.assertFalse(self.store.get_settings()["start_at_login"])

        self.store.update_start_at_login(True)

        self.assertTrue(self.store.get_settings()["start_at_login"])

    def test_settings_survive_store_recreation(self) -> None:
        self.store.update_automation_settings(work_day=2, automation_active=True)
        self.store.update_schedule_time("09:30")

        reopened_store = LocalSettingsStore(self.settings_path)

        self.assertEqual(
            reopened_store.get_settings(),
            {
                "work_day": 2,
                "automation_active": True,
                "start_at_login": False,
                "schedule_time": "09:30",
                "pending_task": None,
                "automation_status": None,
                "calendar_work_days": {},
                "google_account_email": "",
                "form_responses": {
                    "key_tasks": "Did today's assigned task",
                    "challenges": "None",
                    "challenge_resolution": "None",
                    "tomorrow_plan": "do tomorrows assigned task",
                },
            },
        )
        self.assertEqual(
            json.loads(self.settings_path.read_text(encoding="utf-8")),
            {
                "work_day": 2,
                "automation_active": True,
                "start_at_login": False,
                "schedule_time": "09:30",
                "pending_task": None,
                "automation_status": None,
                "calendar_work_days": {},
                "google_account_email": "",
                "form_responses": {
                    "key_tasks": "Did today's assigned task",
                    "challenges": "None",
                    "challenge_resolution": "None",
                    "tomorrow_plan": "do tomorrows assigned task",
                },
            },
        )

    def test_form_responses_are_saved_locally(self) -> None:
        responses = {
            "key_tasks": "Reviewed and fixed the login bug.",
            "challenges": "The test server was unavailable.",
            "challenge_resolution": "Used a local mock response.",
            "tomorrow_plan": "Finish the UI and verify the schedule.",
        }
        self.store.update_form_responses(responses)

        reopened_store = LocalSettingsStore(self.settings_path)

        self.assertEqual(reopened_store.get_settings()["form_responses"], responses)

    def test_calendar_override_is_saved_and_can_be_cleared(self) -> None:
        selected_date = date(2026, 10, 21)
        self.store.set_calendar_work_day(selected_date, 1)

        self.assertEqual(
            self.store.get_settings()["calendar_work_days"], {"2026-10-21": 1}
        )

        self.store.clear_calendar_work_day(selected_date)
        self.assertEqual(self.store.get_settings()["calendar_work_days"], {})

    def test_rejects_incomplete_form_responses(self) -> None:
        with self.assertRaises(ValueError):
            self.store.update_form_responses({"key_tasks": "Only one answer"})

    def test_rejects_invalid_work_day_without_changing_settings(self) -> None:
        with self.assertRaises(ValueError):
            self.store.update_automation_settings(work_day=4, automation_active=True)

        self.assertIsNone(self.store.get_settings()["work_day"])

    def test_disabled_settings_can_have_no_work_day_selected(self) -> None:
        self.store.update_automation_settings(work_day=None, automation_active=False)

        self.assertIsNone(self.store.get_settings()["work_day"])

    def test_automation_cannot_be_enabled_without_a_work_day(self) -> None:
        with self.assertRaises(ValueError):
            self.store.update_automation_settings(
                work_day=None, automation_active=True
            )

    def test_rejects_invalid_schedule_time_without_changing_settings(self) -> None:
        with self.assertRaises(ValueError):
            self.store.update_schedule_time("24:60")

        self.assertIsNone(self.store.get_settings()["schedule_time"])

    def test_account_email_is_saved_but_a_password_is_never_a_setting(self) -> None:
        self.store.update_google_account_email("student@example.com")

        settings = self.store.get_settings()
        raw_settings = self.settings_path.read_text(encoding="utf-8")
        self.assertEqual(settings["google_account_email"], "student@example.com")
        self.assertNotIn("password", raw_settings.lower())

    def test_rejects_an_invalid_account_email(self) -> None:
        with self.assertRaises(ValueError):
            self.store.update_google_account_email("not an email")


if __name__ == "__main__":
    unittest.main()

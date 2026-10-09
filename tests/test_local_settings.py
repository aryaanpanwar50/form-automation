import json
import tempfile
import unittest
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
                "schedule_time": None,
                "pending_task": None,
                "form_responses": {
                    "key_tasks": "Did today's assigned task",
                    "challenges": "None",
                    "challenge_resolution": "None",
                    "tomorrow_plan": "do tomorrows assigned task",
                },
            },
        )

    def test_settings_survive_store_recreation(self) -> None:
        self.store.update_automation_settings(work_day=2, automation_active=True)
        self.store.update_schedule_time("09:30")

        reopened_store = LocalSettingsStore(self.settings_path)

        self.assertEqual(
            reopened_store.get_settings(),
            {
                "work_day": 2,
                "automation_active": True,
                "schedule_time": "09:30",
                "pending_task": None,
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
                "schedule_time": "09:30",
                "pending_task": None,
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


if __name__ == "__main__":
    unittest.main()

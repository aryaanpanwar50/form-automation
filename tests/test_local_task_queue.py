import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from form_automation.local_settings import LocalSettingsStore
from form_automation.local_task_queue import LocalTaskQueue


class LocalTaskQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = LocalSettingsStore(Path(self.temp_dir.name) / "settings.json")
        self.queue = LocalTaskQueue(self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_only_one_pending_task_is_kept(self) -> None:
        self.queue.schedule_next(
            "09:30", work_day=1, now=datetime(2026, 10, 9, 8, 0)
        )
        queued = self.queue.schedule_next(
            "10:00", work_day=2, now=datetime(2026, 10, 9, 8, 1)
        )

        self.assertEqual(
            self.store.get_settings()["pending_task"],
            {"scheduled_date": "2026-10-09", "work_day": 2},
        )
        self.assertEqual(queued["scheduled_date"], "2026-10-09")

    def test_due_task_can_run_later_the_same_day(self) -> None:
        self.queue.schedule_next(
            "09:30", work_day=2, now=datetime(2026, 10, 9, 8, 0)
        )

        task = self.queue.get_due_task(
            "09:30", work_day=2, now=datetime(2026, 10, 9, 15, 0)
        )

        self.assertEqual(
            task, {"scheduled_date": "2026-10-09", "work_day": 2}
        )
        self.assertEqual(self.store.get_settings()["pending_task"], task)

    def test_pending_task_survives_reopening_the_local_store(self) -> None:
        self.queue.schedule_next(
            "09:30", work_day=2, now=datetime(2026, 10, 9, 8, 0)
        )
        reopened_queue = LocalTaskQueue(
            LocalSettingsStore(self.store.settings_path)
        )

        task = reopened_queue.get_due_task(
            "09:30", work_day=2, now=datetime(2026, 10, 9, 15, 0)
        )

        self.assertEqual(
            task, {"scheduled_date": "2026-10-09", "work_day": 2}
        )

    def test_task_from_yesterday_expires_and_waits_for_todays_schedule(self) -> None:
        self.queue.schedule_next(
            "09:30", work_day=1, now=datetime(2026, 10, 8, 8, 0)
        )

        task = self.queue.get_due_task(
            "09:30", work_day=2, now=datetime(2026, 10, 9, 8, 0)
        )

        self.assertIsNone(task)
        self.assertEqual(
            self.store.get_settings()["pending_task"],
            {"scheduled_date": "2026-10-09", "work_day": 2},
        )

    def test_expired_task_does_not_block_todays_normal_submission(self) -> None:
        self.queue.schedule_next(
            "09:30", work_day=1, now=datetime(2026, 10, 8, 8, 0)
        )

        task = self.queue.get_due_task(
            "09:30", work_day=2, now=datetime(2026, 10, 9, 10, 0)
        )

        self.assertEqual(
            task, {"scheduled_date": "2026-10-09", "work_day": 2}
        )

    def test_completing_a_task_queues_only_the_next_occurrence(self) -> None:
        self.queue.schedule_next(
            "09:30", work_day=2, now=datetime(2026, 10, 9, 8, 0)
        )

        next_task = self.queue.complete_task(
            "09:30", work_day=2, now=datetime(2026, 10, 9, 9, 30)
        )

        self.assertEqual(
            next_task, {"scheduled_date": "2026-10-12", "work_day": 2}
        )
        self.assertEqual(self.store.get_settings()["pending_task"], next_task)

    def test_next_task_after_friday_is_monday(self) -> None:
        task = self.queue.schedule_next(
            "09:30", work_day=2, now=datetime(2026, 10, 9, 10, 0)
        )

        self.assertEqual(
            task, {"scheduled_date": "2026-10-12", "work_day": 2}
        )

    def test_missed_friday_task_expires_over_weekend(self) -> None:
        self.queue.schedule_next(
            "09:30", work_day=1, now=datetime(2026, 10, 9, 8, 0)
        )

        task = self.queue.get_due_task(
            "09:30", work_day=2, now=datetime(2026, 10, 10, 10, 0)
        )

        self.assertIsNone(task)
        self.assertEqual(
            self.store.get_settings()["pending_task"],
            {"scheduled_date": "2026-10-12", "work_day": 2},
        )


if __name__ == "__main__":
    unittest.main()

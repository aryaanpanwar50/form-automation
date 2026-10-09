from datetime import date, datetime, time, timedelta
from typing import Any

from .local_settings import LocalSettingsStore, parse_schedule_time


class LocalTaskQueue:
    """Keep at most one scheduled form task in the local settings file."""

    def __init__(self, settings_store: LocalSettingsStore) -> None:
        self.settings_store = settings_store

    @staticmethod
    def _next_weekday(target_date: date) -> date:
        while target_date.weekday() >= 5:
            target_date += timedelta(days=1)
        return target_date

    def schedule_next(
        self, schedule_time: str, work_day: int, now: datetime | None = None
    ) -> dict[str, Any]:
        now = now or datetime.now()
        hour, minute = parse_schedule_time(schedule_time)
        target_date = now.date()
        if now.time() >= time(hour, minute):
            target_date += timedelta(days=1)
        target_date = self._next_weekday(target_date)
        return self.settings_store.set_pending_task(target_date, work_day)

    def get_due_task(
        self,
        schedule_time: str,
        work_day: int,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        now = now or datetime.now()
        settings = self.settings_store.get_settings()
        pending_task = settings["pending_task"]

        if pending_task is not None:
            task_date = date.fromisoformat(pending_task["scheduled_date"])
            if task_date < now.date() or task_date.weekday() >= 5:
                self.settings_store.clear_pending_task()
                pending_task = None
            elif task_date > now.date():
                return None

        if pending_task is None:
            task_date = self._next_weekday(now.date())
            pending_task = self.settings_store.set_pending_task(task_date, work_day)
            if task_date > now.date():
                return None

        hour, minute = parse_schedule_time(schedule_time)
        if now.time() < time(hour, minute):
            return None

        return pending_task

    def complete_task(
        self, schedule_time: str, work_day: int, now: datetime | None = None
    ) -> dict[str, Any]:
        return self.schedule_next(schedule_time, work_day, now)

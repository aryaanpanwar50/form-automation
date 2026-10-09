import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .local_paths import APP_DATA_DIRECTORY

DEFAULT_SETTINGS_PATH = APP_DATA_DIRECTORY / "settings.json"
DEFAULT_FORM_RESPONSES: dict[str, str] = {
    "key_tasks": "Did today's assigned task",
    "challenges": "None",
    "challenge_resolution": "None",
    "tomorrow_plan": "do tomorrows assigned task",
}
DEFAULT_SETTINGS: dict[str, Any] = {
    "work_day": None,
    "automation_active": False,
    "schedule_time": None,
    "pending_task": None,
    "form_responses": DEFAULT_FORM_RESPONSES,
}


def parse_schedule_time(schedule_time: str) -> tuple[int, int]:
    if not re.fullmatch(r"\d{2}:\d{2}", schedule_time):
        raise ValueError("schedule_time must be in HH:MM format")

    hour, minute = map(int, schedule_time.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("schedule_time must be in HH:MM format")

    return hour, minute


class LocalSettingsStore:
    """Store the desktop user's settings in a local JSON file."""

    def __init__(self, settings_path: Path = DEFAULT_SETTINGS_PATH) -> None:
        self.settings_path = Path(settings_path)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.settings_path.exists():
            self._write_settings(DEFAULT_SETTINGS.copy())

    def _read_settings(self) -> dict[str, Any]:
        try:
            settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RuntimeError(
                f"Local settings file is not valid JSON: {self.settings_path}"
            ) from error

        result = {**DEFAULT_SETTINGS, **settings}
        saved_responses = result["form_responses"]
        if not isinstance(saved_responses, dict):
            raise RuntimeError("Local form responses are not a JSON object")
        result["form_responses"] = {
            **DEFAULT_FORM_RESPONSES,
            **saved_responses,
        }
        return result

    def _write_settings(self, settings: dict[str, Any]) -> None:
        temporary_path = self.settings_path.with_suffix(
            f"{self.settings_path.suffix}.tmp"
        )
        temporary_path.write_text(
            json.dumps(settings, indent=2) + "\n", encoding="utf-8"
        )
        temporary_path.replace(self.settings_path)

    def get_settings(self) -> dict[str, Any]:
        return self._read_settings()

    def update_automation_settings(
        self, work_day: int | None, automation_active: bool
    ) -> None:
        if work_day not in (1, 2, 3) and not (
            work_day is None and not automation_active
        ):
            raise ValueError("work_day must be 1, 2, or 3")

        settings = self._read_settings()
        settings["work_day"] = work_day
        settings["automation_active"] = bool(automation_active)
        self._write_settings(settings)

    def update_schedule_time(self, schedule_time: str) -> None:
        parse_schedule_time(schedule_time)
        settings = self._read_settings()
        settings["schedule_time"] = schedule_time
        self._write_settings(settings)

    def update_form_responses(self, responses: dict[str, str]) -> None:
        if set(responses) != set(DEFAULT_FORM_RESPONSES):
            raise ValueError("form_responses must contain all four form fields")
        if any(not isinstance(value, str) for value in responses.values()):
            raise ValueError("form responses must be text")

        settings = self._read_settings()
        settings["form_responses"] = responses.copy()
        self._write_settings(settings)

    def set_pending_task(self, scheduled_date: date, work_day: int) -> dict[str, Any]:
        if work_day not in (1, 2, 3):
            raise ValueError("work_day must be 1, 2, or 3")

        task = {"scheduled_date": scheduled_date.isoformat(), "work_day": work_day}
        settings = self._read_settings()
        settings["pending_task"] = task
        self._write_settings(settings)
        return task

    def clear_pending_task(self) -> None:
        settings = self._read_settings()
        settings["pending_task"] = None
        self._write_settings(settings)


def get_settings_store() -> LocalSettingsStore:
    return LocalSettingsStore()

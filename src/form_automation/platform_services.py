"""Small platform adapters for paths, secure credentials, and sign-in startup.

Shared application code must not need to know whether it runs on Windows or macOS.
Secrets remain in the operating system's credential vault, never in settings.json.
"""

from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def _safe_user_id(user_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", user_id)


@dataclass(frozen=True)
class AppPaths:
    """Per-user locations following each operating system's conventions."""

    app_data_directory: Path

    @classmethod
    def create(
        cls,
        *,
        system_name: str | None = None,
        environment: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> "AppPaths":
        system_name = system_name or platform.system()
        environment = environment if environment is not None else os.environ
        home = home or Path.home()
        if system_name == "Windows":
            root = Path(environment.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        elif system_name == "Darwin":
            root = home / "Library" / "Application Support"
        else:
            root = Path(environment.get("XDG_DATA_HOME", str(home / ".local" / "share")))
        return cls(root / "FormAutomation")


class MacOSKeychainCredentialStore:
    """Credential store backed by the current macOS user's Keychain."""

    def __init__(self, backend=None) -> None:
        if backend is None:
            import keyring

            backend = keyring
        self._backend = backend

    @staticmethod
    def _service_name(user_id: str) -> str:
        return f"FormAutomation.GooglePassword.{_safe_user_id(user_id)}"

    def save(self, user_id: str, password: str) -> None:
        if not password:
            raise ValueError("Password cannot be empty")
        try:
            self._backend.set_password(self._service_name(user_id), user_id, password)
        except Exception as error:
            raise RuntimeError(
                "macOS Keychain could not save the automatic reconnect password."
            ) from error

    def get(self, user_id: str) -> str | None:
        try:
            return self._backend.get_password(self._service_name(user_id), user_id)
        except Exception as error:
            raise RuntimeError(
                "macOS Keychain could not read the automatic reconnect password."
            ) from error

    def clear(self, user_id: str) -> None:
        try:
            self._backend.delete_password(self._service_name(user_id), user_id)
        except Exception as error:
            if error.__class__.__name__ != "PasswordDeleteError":
                raise RuntimeError(
                    "macOS Keychain could not remove the automatic reconnect password."
                ) from error


@dataclass(frozen=True)
class StartupService:
    """Platform-neutral startup policy. Startup always requires user opt-in."""

    system_name: str | None = None

    @property
    def supported(self) -> bool:
        return (self.system_name or platform.system()) in {"Windows", "Darwin"}

    def should_enable_at_launch(self, user_enabled: bool) -> bool:
        return self.supported and bool(user_enabled)

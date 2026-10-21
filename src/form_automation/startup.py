"""Manage the app's opt-in per-user launch-at-sign-in entry."""

import os
import platform
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

from .runtime import is_packaged_application

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "FormAutomation"
MACOS_LAUNCH_AGENT = "com.formautomation.app.plist"


def startup_command(
    executable: str | Path | None = None,
    project_directory: str | Path | None = None,
    *,
    packaged: bool | None = None,
) -> tuple[str, str, str]:
    """Return the executable, arguments, and working directory for autostart."""
    current_executable = Path(executable or sys.executable).resolve()
    app_directory = Path(project_directory or Path(__file__).resolve().parents[2])
    is_packaged = (
        is_packaged_application(current_executable)
        if packaged is None
        else packaged
    )

    if is_packaged:
        target = current_executable
        arguments: list[str] = []
        working_directory = current_executable.parent
    else:
        pythonw = current_executable.with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else current_executable
        arguments = ["-m", "form_automation"]
        working_directory = app_directory

    command = subprocess.list2cmdline([str(target), *arguments])
    return str(target), command, str(working_directory)


def enable_windows_startup() -> None:
    """Add this app to the current user's Windows sign-in startup entries."""
    if os.name != "nt":
        return

    import winreg

    _target, command, _working_directory = startup_command()
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, command)


def disable_windows_startup() -> None:
    """Remove this app from the current user's Windows startup entries."""
    if os.name != "nt":
        return

    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        pass


def _macos_launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / MACOS_LAUNCH_AGENT


def enable_macos_startup() -> None:
    """Create a per-user LaunchAgent only after explicit user opt-in."""
    _target, command, working_directory = startup_command()
    launch_agent = _macos_launch_agent_path()
    launch_agent.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": "com.formautomation.app",
        "ProgramArguments": shlex.split(command),
        "WorkingDirectory": working_directory,
        "RunAtLoad": True,
    }
    with launch_agent.open("wb") as stream:
        plistlib.dump(payload, stream)


def disable_macos_startup() -> None:
    """Remove the app's own per-user LaunchAgent when startup is disabled."""
    _macos_launch_agent_path().unlink(missing_ok=True)


def apply_startup_preference(enabled: bool) -> None:
    """Reconcile the OS startup entry with the user's saved preference."""
    if os.name == "nt":
        (enable_windows_startup if enabled else disable_windows_startup)()
    elif platform.system() == "Darwin":
        (enable_macos_startup if enabled else disable_macos_startup)()

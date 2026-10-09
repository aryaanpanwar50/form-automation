"""Register the desktop app to launch when the current Windows user signs in."""

import os
import subprocess
import sys
from pathlib import Path

from .runtime import is_packaged_application

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "FormAutomation"


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

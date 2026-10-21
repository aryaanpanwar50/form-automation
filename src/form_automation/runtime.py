"""Runtime helpers shared by source installs and packaged desktop builds."""

import os
import sys
from pathlib import Path


def is_packaged_application(
    executable: str | Path | None = None,
    *,
    frozen: bool | None = None,
) -> bool:
    current_executable = Path(executable or sys.executable)
    runtime_is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    # Tests and cross-platform tooling can pass a Windows path while running on
    # macOS/Linux, where pathlib does not treat backslashes as separators.
    executable_name = str(current_executable).replace("\\", "/").rsplit("/", 1)[-1]
    return bool(
        runtime_is_frozen
        or "__compiled__" in globals()
        or not Path(executable_name).stem.lower().startswith("python")
    )


def configure_playwright_browser_path(
    executable: str | Path | None = None,
    *,
    packaged: bool | None = None,
) -> str | None:
    """Point packaged apps at bundled Playwright browsers beside their executable."""
    current_executable = Path(executable or sys.executable).resolve()
    if packaged is None:
        packaged = is_packaged_application(current_executable)
    if not packaged:
        return None

    browser_directory = current_executable.parent / "ms-playwright"
    if not browser_directory.is_dir():
        return None

    browser_path = str(browser_directory)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browser_path
    return browser_path

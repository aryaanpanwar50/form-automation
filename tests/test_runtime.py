import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from form_automation.runtime import (
    configure_playwright_browser_path,
    is_packaged_application,
)


class RuntimePackagingTests(unittest.TestCase):
    def test_detects_source_python_as_unpacked(self) -> None:
        self.assertFalse(
            is_packaged_application(executable=r"C:\Python\python.exe", frozen=False)
        )

    def test_detects_named_executable_as_packaged(self) -> None:
        self.assertTrue(
            is_packaged_application(
                executable=r"C:\Program Files\Form Automation\FormAutomation.exe",
                frozen=False,
            )
        )

    def test_packaged_app_uses_browser_bundle_next_to_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "FormAutomation.exe"
            browser_bundle = root / "ms-playwright"
            executable.touch()
            browser_bundle.mkdir()
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

                result = configure_playwright_browser_path(
                    executable=executable,
                    packaged=True,
                )

                self.assertEqual(result, str(browser_bundle))
                self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], result)

    def test_source_app_does_not_override_browser_path(self) -> None:
        with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": "custom-path"}):
            result = configure_playwright_browser_path(
                executable=r"C:\Python\python.exe",
                packaged=False,
            )

            self.assertIsNone(result)
            self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], "custom-path")


if __name__ == "__main__":
    unittest.main()

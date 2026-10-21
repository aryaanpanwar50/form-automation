import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from form_automation.startup import enable_macos_startup, startup_command


class WindowsStartupCommandTests(unittest.TestCase):
    def test_source_install_uses_pythonw_and_module_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "Scripts" / "python.exe"
            executable.parent.mkdir()
            executable.touch()
            pythonw = executable.with_name("pythonw.exe")
            pythonw.touch()
            project = root / "Form Automation"
            project.mkdir()

            target, command, working_directory = startup_command(
                executable=executable,
                project_directory=project,
                packaged=False,
            )

            self.assertEqual(target, str(pythonw.resolve()))
            self.assertTrue(command.endswith("-m form_automation"))
            self.assertEqual(working_directory, str(project))

    def test_packaged_install_launches_the_executable_directly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "Form Automation.exe"
            executable.touch()

            target, command, working_directory = startup_command(
                executable=executable,
                packaged=True,
            )

            self.assertEqual(target, str(executable.resolve()))
            self.assertEqual(command, f'"{executable.resolve()}"')
            self.assertEqual(working_directory, str(executable.resolve().parent))

    def test_macos_source_launch_agent_keeps_the_module_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            launch_agent = Path(directory) / "com.formautomation.app.plist"
            with (
                patch("form_automation.startup._macos_launch_agent_path", return_value=launch_agent),
                patch(
                    "form_automation.startup.startup_command",
                    return_value=("/usr/bin/python3", "/usr/bin/python3 -m form_automation", "/tmp/project"),
                ),
            ):
                enable_macos_startup()

            import plistlib

            with launch_agent.open("rb") as stream:
                payload = plistlib.load(stream)
            self.assertEqual(
                payload["ProgramArguments"],
                ["/usr/bin/python3", "-m", "form_automation"],
            )


if __name__ == "__main__":
    unittest.main()

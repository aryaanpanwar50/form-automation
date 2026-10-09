import tempfile
import unittest
from pathlib import Path

from form_automation.startup import startup_command


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


if __name__ == "__main__":
    unittest.main()

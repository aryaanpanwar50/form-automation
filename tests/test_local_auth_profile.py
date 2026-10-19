import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from form_automation.local_auth_state import (
    clear_local_auth_profile,
    has_local_auth_profile,
    mark_local_auth_profile,
    profile_directory,
)


class LocalAuthProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.profile_root = Path(self.temp_dir.name) / "google-profile"
        self.profile_patch = patch(
            "form_automation.local_auth_state.GOOGLE_PROFILE_DIRECTORY",
            self.profile_root,
        )
        self.profile_patch.start()

    def tearDown(self) -> None:
        self.profile_patch.stop()
        self.temp_dir.cleanup()

    def test_marks_a_connected_dedicated_profile(self) -> None:
        mark_local_auth_profile("default")

        self.assertTrue(has_local_auth_profile("default"))
        self.assertTrue((profile_directory("default") / ".connected").is_file())

    def test_removing_profile_removes_only_the_selected_profile(self) -> None:
        mark_local_auth_profile("default")
        other_profile = profile_directory("other")
        other_profile.mkdir(parents=True)
        (other_profile / ".connected").write_text("connected\n", encoding="utf-8")

        clear_local_auth_profile("default")

        self.assertFalse(profile_directory("default").exists())
        self.assertTrue(has_local_auth_profile("other"))


if __name__ == "__main__":
    unittest.main()

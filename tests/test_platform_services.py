import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from form_automation import platform_services


class AppPathsTests(unittest.TestCase):
    def test_windows_uses_local_app_data(self) -> None:
        paths = platform_services.AppPaths.create(
            system_name="Windows",
            environment={"LOCALAPPDATA": r"C:\Users\A\AppData\Local"},
            home=Path("C:/Users/A"),
        )

        self.assertEqual(
            paths.app_data_directory,
            Path(r"C:\Users\A\AppData\Local") / "FormAutomation",
        )

    def test_macos_uses_application_support(self) -> None:
        paths = platform_services.AppPaths.create(
            system_name="Darwin", environment={}, home=Path("/Users/aryaan")
        )

        self.assertEqual(
            paths.app_data_directory,
            Path("/Users/aryaan/Library/Application Support/FormAutomation"),
        )

    def test_linux_uses_xdg_data_home(self) -> None:
        paths = platform_services.AppPaths.create(
            system_name="Linux",
            environment={"XDG_DATA_HOME": "/tmp/data"},
            home=Path("/home/aryaan"),
        )

        self.assertEqual(paths.app_data_directory, Path("/tmp/data/FormAutomation"))


class StartupServiceTests(unittest.TestCase):
    def test_startup_is_not_enabled_automatically(self) -> None:
        startup = platform_services.StartupService(system_name="Windows")

        self.assertFalse(startup.should_enable_at_launch(False))

    def test_startup_is_enabled_only_when_user_preference_is_true(self) -> None:
        startup = platform_services.StartupService(system_name="Windows")

        self.assertTrue(startup.should_enable_at_launch(True))

    def test_macos_startup_is_supported(self) -> None:
        self.assertTrue(platform_services.StartupService(system_name="Darwin").supported)

    def test_desktop_entry_point_uses_the_disabled_default_startup_preference(self) -> None:
        from form_automation import desktop

        with tempfile.TemporaryDirectory() as directory:
            settings_store = Mock()
            settings_store.get_settings.return_value = {"start_at_login": False}
            with (
                patch.object(desktop, "APP_DATA_DIRECTORY", Path(directory)),
                patch.object(desktop, "get_settings_store", return_value=settings_store),
                patch.object(desktop, "apply_startup_preference") as apply_preference,
                patch.object(desktop.logging, "basicConfig"),
                patch.object(desktop, "configure_playwright_browser_path"),
                patch.object(desktop, "_configure_font"),
                patch.object(desktop, "make_app_icon"),
                patch.object(desktop, "MainWindow") as window_class,
                patch.object(desktop, "QApplication") as application_class,
                patch.object(desktop.sys, "exit"),
            ):
                application_class.return_value.exec.return_value = 0
                desktop.main()

        apply_preference.assert_called_once_with(False)
        window_class.return_value.show.assert_called_once_with()


class MacOSKeychainCredentialStoreTests(unittest.TestCase):
    def test_save_uses_the_keychain_backend_without_a_command_line(self) -> None:
        backend = Mock()
        store = platform_services.MacOSKeychainCredentialStore(backend=backend)

        store.save("default", "secret-password")

        backend.set_password.assert_called_once_with(
            "FormAutomation.GooglePassword.default", "default", "secret-password"
        )

    def test_missing_keychain_item_returns_none(self) -> None:
        backend = Mock()
        backend.get_password.return_value = None
        store = platform_services.MacOSKeychainCredentialStore(backend=backend)

        self.assertIsNone(store.get("default"))


if __name__ == "__main__":
    unittest.main()

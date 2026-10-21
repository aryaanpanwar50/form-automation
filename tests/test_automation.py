import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from form_automation.scripts.automation import (
    GoogleVerificationRequiredError,
    FormUnavailableError,
    SessionExpiredError,
    _fill_form,
    _check_form_connection,
    _reconnect_google_account,
    _require_form_checkbox,
    _save_failure_diagnostics,
)


CHECKBOX_NAME = "Record aryaan.panwar.s66@"
RESPONSES = {
    "key_tasks": "Completed the assigned task.",
    "challenges": "None.",
    "challenge_resolution": "None needed.",
    "tomorrow_plan": "Start the next assigned task.",
}


class FakeLocator:
    def __init__(self, page, role: str, name: str) -> None:
        self.page = page
        self.role = role
        self.name = name

    def is_checked(self, **_kwargs) -> bool:
        return False

    def is_visible(self, **_kwargs) -> bool:
        return True

    def click(self) -> None:
        self.page.actions.append(("click", self.role, self.name))

    def fill(self, value: str) -> None:
        self.page.actions.append(("fill", self.role, self.name, value))


class FakePage:
    def __init__(self, url: str = "https://docs.google.com/forms/d/e/test/viewform") -> None:
        self.actions: list[tuple] = []
        self.url = url

    def goto(self, url: str, **_kwargs) -> None:
        self.actions.append(("goto", url))

    def get_by_role(self, role: str, name: str) -> FakeLocator:
        return FakeLocator(self, role, name)

    def wait_for_function(self, script: str, **_kwargs) -> None:
        if "response has been recorded" in script:
            self.actions.append(("wait_for_confirmation",))


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.pages = [page]
        self.closed = False

    def new_page(self) -> FakePage:
        return self.pages[0]

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.launch_options = None

    def launch_persistent_context(self, path: str, **kwargs) -> FakeContext:
        self.launch_options = {"path": path, **kwargs}
        return self.context


class FakePlaywright:
    def __init__(self) -> None:
        self.page = FakePage()
        self.context = FakeContext(self.page)
        self.chromium = FakeChromium(self.context)


class DiagnosticPage:
    def screenshot(self, *, path: str, **_kwargs) -> None:
        Path(path).write_bytes(b"screenshot")


class DiagnosticTrace:
    def __init__(self) -> None:
        self.started = None
        self.stopped = None

    def start(self, **kwargs) -> None:
        self.started = kwargs

    def stop(self, *, path: str | None = None) -> None:
        self.stopped = path
        if path:
            Path(path).write_bytes(b"trace")


class DiagnosticContext:
    def __init__(self) -> None:
        self.tracing = DiagnosticTrace()


class SignInLocator:
    def __init__(self, page, description: str) -> None:
        self.page = page
        self.description = description

    def click(self, **_kwargs) -> None:
        self.page.actions.append(("click", self.description))

    def fill(self, value: str, **_kwargs) -> None:
        self.page.actions.append(("fill", self.description, value))


class SignInPage:
    def __init__(self, account_picker: bool = True) -> None:
        self.account_picker = account_picker
        self.actions: list[tuple] = []
        self.url = "https://accounts.google.com/v3/signin"

    def get_by_text(self, text: str, **_kwargs) -> SignInLocator:
        if not self.account_picker:
            raise PlaywrightTimeoutError("not an account picker")
        return SignInLocator(self, f"account:{text}")

    def locator(self, selector: str) -> SignInLocator:
        return SignInLocator(self, selector)

    def get_by_role(self, role: str, name: str) -> SignInLocator:
        return SignInLocator(self, f"{role}:{name}")

    def wait_for_function(self, _script: str, **_kwargs) -> None:
        self.actions.append(("wait_for_signed_in",))
        self.url = "https://docs.google.com/forms/d/e/test/viewform"


class FormAutomationTests(unittest.TestCase):
    def run_form(self, work_day: int, progress_reporter=None) -> FakePlaywright:
        playwright = FakePlaywright()
        with patch("form_automation.scripts.automation.profile_directory", return_value="profile"):
            _fill_form(
                playwright,
                work_day,
                RESPONSES,
                progress_reporter=progress_reporter,
            )
        self.assertEqual(
            playwright.chromium.launch_options,
            {"path": "profile", "headless": True, "channel": "chromium"},
        )
        self.assertTrue(playwright.context.closed)
        return playwright

    def test_campus_holiday_selects_next_then_submits(self) -> None:
        playwright = self.run_form(1)
        self.assertEqual(
            playwright.page.actions[1:],
            [
                ("click", "checkbox", CHECKBOX_NAME),
                ("click", "radio", "It was a campus holiday"),
                ("click", "button", "Next"),
                ("click", "button", "Submit"),
                ("wait_for_confirmation",),
            ],
        )

    def test_working_day_fills_all_responses_then_submits(self) -> None:
        playwright = self.run_form(2)
        self.assertIn(("click", "button", "Submit"), playwright.page.actions)
        self.assertIn(
            ("fill", "textbox", "What were your key tasks for", RESPONSES["key_tasks"]),
            playwright.page.actions,
        )
        self.assertEqual(sum(action[0] == "fill" for action in playwright.page.actions), 4)

    def test_leave_or_absence_selects_next_then_submits(self) -> None:
        playwright = self.run_form(3)
        self.assertEqual(
            playwright.page.actions[1:],
            [
                ("click", "checkbox", CHECKBOX_NAME),
                (
                    "click",
                    "radio",
                    "It was a working day, but I was on leave or absent",
                ),
                ("click", "button", "Next"),
                ("click", "button", "Submit"),
                ("wait_for_confirmation",),
            ],
        )

    def test_reports_each_submission_stage_without_recording_response_text(self) -> None:
        stages: list[str] = []

        self.run_form(1, stages.append)

        self.assertEqual(
            stages,
            [
                "Opening Google Form.",
                "Checking Google session.",
                "Checking form account checkbox.",
                "Selecting form account checkbox.",
                "Selecting Campus holiday.",
                "Opening confirmation page.",
                "Submitting Google Form.",
                "Confirming submitted response.",
            ],
        )
        self.assertTrue(all(RESPONSES["key_tasks"] not in stage for stage in stages))

    def test_connection_test_checks_every_required_control_without_submitting(self) -> None:
        playwright = FakePlaywright()
        stages: list[str] = []
        with patch("form_automation.scripts.automation.profile_directory", return_value="profile"):
            message = _check_form_connection(playwright, progress_reporter=stages.append)

        self.assertEqual(message, "Form connection test passed. No response was submitted.")
        self.assertEqual(playwright.page.actions, [("goto", "https://docs.google.com/forms/d/e/1FAIpQLSc8RRUAG8n8nPB9dm21m_MxwHQ-JuDnEj7GnvwEkWXykkKFuQ/viewform")])
        self.assertTrue(playwright.context.closed)
        self.assertIn("Checking Campus holiday option.", stages)
        self.assertIn("Checking Working day - present option.", stages)
        self.assertIn("Checking Working day - leave or absent option.", stages)
        self.assertEqual(stages[-1], "Form connection test passed. No response was submitted.")

    def test_connection_test_identifies_a_missing_radio_option(self) -> None:
        page = FakePage()
        original_get_by_role = page.get_by_role

        def get_by_role(role: str, name: str):
            if role == "radio" and name == "It was a campus holiday":
                locator = FakeLocator(page, role, name)
                locator.is_visible = lambda **_kwargs: (_ for _ in ()).throw(
                    PlaywrightTimeoutError("missing radio")
                )
                return locator
            return original_get_by_role(role, name)

        page.get_by_role = get_by_role
        playwright = FakePlaywright()
        playwright.page = page
        playwright.context = FakeContext(page)
        playwright.chromium = FakeChromium(playwright.context)

        with (
            patch("form_automation.scripts.automation.profile_directory", return_value="profile"),
            patch("form_automation.scripts.automation._save_failure_diagnostics", return_value=""),
            self.assertRaisesRegex(FormUnavailableError, "Campus holiday.*not found"),
        ):
            _check_form_connection(playwright)

    def test_failure_diagnostics_save_a_local_screenshot_and_trace(self) -> None:
        context = DiagnosticContext()
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch(
                "form_automation.scripts.automation.DIAGNOSTICS_DIRECTORY",
                Path(temporary_directory),
            ):
                message = _save_failure_diagnostics(
                    context, DiagnosticPage(), "selecting campus holiday", True
                )

            files = {path.suffix for path in Path(temporary_directory).iterdir()}
        self.assertIn(".png", files)
        self.assertIn(".zip", files)
        self.assertIn("FormAutomation\\diagnostics", message)

    def test_form_error_includes_the_stage_that_failed(self) -> None:
        page = FakePage()
        page.get_by_role = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PlaywrightTimeoutError("missing radio")
        )
        playwright = FakePlaywright()
        playwright.page = page
        playwright.context = FakeContext(page)
        playwright.chromium = FakeChromium(playwright.context)

        with (
            patch(
                "form_automation.scripts.automation.profile_directory",
                return_value="profile",
            ),
            patch(
                "form_automation.scripts.automation._save_failure_diagnostics",
                return_value="",
            ),
            self.assertRaisesRegex(FormUnavailableError, "checking form account checkbox"),
        ):
            _fill_form(playwright, 1, RESPONSES)

    def test_sign_in_redirect_is_reported_as_an_expired_session(self) -> None:
        page = FakePage("https://accounts.google.com/v3/signin")

        with self.assertRaises(SessionExpiredError):
            _require_form_checkbox(page)

    def test_missing_form_control_is_not_misreported_as_a_session_error(self) -> None:
        page = FakePage()
        locator = page.get_by_role("checkbox", CHECKBOX_NAME)
        locator.is_checked = lambda **_kwargs: (_ for _ in ()).throw(
            PlaywrightTimeoutError("missing")
        )
        page.get_by_role = lambda _role, name=None: locator

        with self.assertRaisesRegex(RuntimeError, "checkbox changed"):
            _require_form_checkbox(page)

    def test_saved_password_reconnects_from_google_account_picker(self) -> None:
        page = SignInPage()

        _reconnect_google_account(page, "student@example.com", "not-logged")

        self.assertEqual(
            page.actions,
            [
                ("click", "account:student@example.com"),
                ("fill", "input[type='password']", "not-logged"),
                ("click", "button:Next"),
                ("wait_for_signed_in",),
            ],
        )

    def test_saved_password_uses_direct_email_page_when_no_account_picker_exists(self) -> None:
        page = SignInPage(account_picker=False)

        _reconnect_google_account(page, "student@example.com", "not-logged")

        self.assertEqual(page.actions[0], ("fill", "input[type='email']", "student@example.com"))
        self.assertIn(("fill", "input[type='password']", "not-logged"), page.actions)

    def test_reconnect_requires_an_explicitly_saved_email_and_password(self) -> None:
        with self.assertRaisesRegex(SessionExpiredError, "Automatic reconnect"):
            _reconnect_google_account(SignInPage(), "student@example.com", None)

    def test_reconnect_does_not_attempt_to_bypass_google_verification(self) -> None:
        page = SignInPage()
        page.locator = lambda _selector: (_ for _ in ()).throw(PlaywrightTimeoutError("MFA"))

        with self.assertRaises(GoogleVerificationRequiredError):
            _reconnect_google_account(page, "student@example.com", "not-logged")


if __name__ == "__main__":
    unittest.main()

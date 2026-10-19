import unittest
from unittest.mock import patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from form_automation.scripts.automation import (
    GoogleVerificationRequiredError,
    SessionExpiredError,
    _fill_form,
    _reconnect_google_account,
    _require_form_checkbox,
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
    def run_form(self, work_day: int) -> FakePlaywright:
        playwright = FakePlaywright()
        with patch("form_automation.scripts.automation.profile_directory", return_value="profile"):
            _fill_form(playwright, work_day, RESPONSES)
        self.assertEqual(
            playwright.chromium.launch_options,
            {"path": "profile", "headless": False, "channel": "chromium"},
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

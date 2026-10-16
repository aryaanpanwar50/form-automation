import unittest

from form_automation.scripts.automation import _fill_form


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

    def is_checked(self) -> bool:
        return False

    def click(self) -> None:
        self.page.actions.append(("click", self.role, self.name))

    def fill(self, value: str) -> None:
        self.page.actions.append(("fill", self.role, self.name, value))


class FakePage:
    def __init__(self) -> None:
        self.actions: list[tuple] = []

    def goto(self, url: str, **_kwargs) -> None:
        self.actions.append(("goto", url))

    def get_by_role(self, role: str, name: str) -> FakeLocator:
        return FakeLocator(self, role, name)

    def wait_for_function(self, script: str, **_kwargs) -> None:
        if "response has been recorded" in script:
            self.actions.append(("wait_for_confirmation",))


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.closed = False

    def new_page(self) -> FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.storage_state = None
        self.closed = False

    def new_context(self, *, storage_state: dict) -> FakeContext:
        self.storage_state = storage_state
        return self.context

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.launch_options = None

    def launch(self, **kwargs) -> FakeBrowser:
        self.launch_options = kwargs
        return self.browser


class FakePlaywright:
    def __init__(self) -> None:
        self.page = FakePage()
        self.context = FakeContext(self.page)
        self.browser = FakeBrowser(self.context)
        self.chromium = FakeChromium(self.browser)


class FormAutomationTests(unittest.TestCase):
    def run_form(self, work_day: int) -> FakePlaywright:
        playwright = FakePlaywright()
        _fill_form(playwright, work_day, {"cookies": []}, RESPONSES)
        self.assertEqual(
            playwright.chromium.launch_options,
            {"headless": True, "channel": "chromium"},
        )
        self.assertTrue(playwright.context.closed)
        self.assertTrue(playwright.browser.closed)
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

        self.assertEqual(
            playwright.page.actions[1:],
            [
                ("click", "checkbox", CHECKBOX_NAME),
                ("click", "radio", "It was a working day, and I"),
                ("click", "button", "Next"),
                (
                    "fill",
                    "textbox",
                    "What were your key tasks for",
                    RESPONSES["key_tasks"],
                ),
                (
                    "fill",
                    "textbox",
                    "What challenges/problems did",
                    RESPONSES["challenges"],
                ),
                (
                    "fill",
                    "textbox",
                    "What challenges/problems you",
                    RESPONSES["challenge_resolution"],
                ),
                (
                    "fill",
                    "textbox",
                    "What is your plan for the",
                    RESPONSES["tomorrow_plan"],
                ),
                ("click", "button", "Next"),
                ("click", "button", "Submit"),
                ("wait_for_confirmation",),
            ],
        )

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


if __name__ == "__main__":
    unittest.main()

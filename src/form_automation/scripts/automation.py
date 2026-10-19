from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Playwright, TimeoutError as PlaywrightTimeoutError, sync_playwright

from ..local_credentials import CredentialStoreError, get_google_password
from ..local_auth_state import profile_directory
from ..local_paths import LOCAL_PROFILE_ID

FORM_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSc8RRUAG8n8nPB9dm21m_MxwHQ-JuDnEj7GnvwEkWXykkKFuQ"
    "/viewform"
)
ACCOUNT_CHECKBOX = "Record aryaan.panwar.s66@"


class AutomationError(RuntimeError):
    """A user-visible failure while loading or submitting the form."""


class SessionExpiredError(AutomationError):
    """Google redirected the saved profile to an account sign-in page."""


class FormUnavailableError(AutomationError):
    """The expected Google Form controls are unavailable."""


class GoogleVerificationRequiredError(SessionExpiredError):
    """Google needs a manual verification step which automation must not bypass."""


def _is_google_sign_in_page(page) -> bool:
    return urlparse(page.url).hostname == "accounts.google.com"


def _require_form_checkbox(page):
    if _is_google_sign_in_page(page):
        raise SessionExpiredError(
            "Google session expired. Reconnect your Google account to submit the pending form."
        )
    checkbox = page.get_by_role("checkbox", name=ACCOUNT_CHECKBOX)
    try:
        checkbox.is_checked(timeout=15000)
    except PlaywrightTimeoutError as error:
        if _is_google_sign_in_page(page):
            raise SessionExpiredError(
                "Google session expired. Reconnect your Google account to submit the pending form."
            ) from error
        raise FormUnavailableError(
            "The Google Form could not be loaded or its account checkbox changed."
        ) from error
    return checkbox


def _reconnect_google_account(page, account_email: str, password: str | None) -> None:
    """Use the explicitly saved Credential Manager password on Google's sign-in UI.

    This intentionally does not attempt to answer MFA, CAPTCHA, recovery, or
    device-approval prompts.  Those must stay manual Google security checks.
    """
    if not account_email or not password:
        raise SessionExpiredError(
            "Google session expired. Set up Automatic reconnect or reconnect the Google account manually."
        )

    try:
        # The usual expired-session page is the account chooser.  Clicking the
        # remembered account advances to its password field.
        page.get_by_text(account_email, exact=True).click(timeout=5000)
    except PlaywrightTimeoutError:
        # A less common direct sign-in page asks for the email first.
        try:
            email_input = page.locator("input[type='email']")
            email_input.fill(account_email, timeout=5000)
            page.get_by_role("button", name="Next").click(timeout=5000)
        except PlaywrightTimeoutError as error:
            raise GoogleVerificationRequiredError(
                "Google needs manual sign-in or verification. Click Change Google account to reconnect."
            ) from error

    try:
        password_input = page.locator("input[type='password']")
        password_input.fill(password, timeout=15000)
        page.get_by_role("button", name="Next").click(timeout=5000)
        page.wait_for_function(
            "() => location.hostname !== 'accounts.google.com'", timeout=20000
        )
    except PlaywrightTimeoutError as error:
        raise GoogleVerificationRequiredError(
            "Google requires verification or did not accept the saved password. "
            "Click Change Google account to finish reconnecting manually."
        ) from error


def _restore_session_if_needed(page, account_email: str, user_id: str) -> None:
    if not _is_google_sign_in_page(page):
        return
    try:
        password = get_google_password(user_id)
    except CredentialStoreError as error:
        raise SessionExpiredError(
            "Google session expired and the saved automatic reconnect password is unavailable."
        ) from error
    _reconnect_google_account(page, account_email, password)
    page.goto(FORM_URL, wait_until="domcontentloaded")


def _fill_form(
    playwright: Playwright,
    work_day: int,
    form_responses: dict[str, str],
    user_id: str = LOCAL_PROFILE_ID,
    account_email: str = "",
) -> None:
    context = playwright.chromium.launch_persistent_context(
        str(profile_directory(user_id)), headless=False, channel="chromium"
    )
    page = context.pages[0] if context.pages else context.new_page()

    try:
        page.goto(FORM_URL, wait_until="domcontentloaded")
        _restore_session_if_needed(page, account_email, user_id)
        checkbox = _require_form_checkbox(page)
        if not checkbox.is_checked():
            checkbox.click()
            page.wait_for_function(
                """() => [...document.querySelectorAll('[role="checkbox"]')].some(
                    element => element.getAttribute('aria-label')?.startsWith('Record aryaan.panwar.s66@')
                        && element.getAttribute('aria-checked') === 'true'
                )""",
                timeout=15000,
            )

        match work_day:
            case 1:
                page.get_by_role("radio", name="It was a campus holiday").click()
                page.get_by_role("button", name="Next").click()
                page.get_by_role("button", name="Submit").click()
            case 2:
                page.get_by_role("radio", name="It was a working day, and I").click()
                page.get_by_role("button", name="Next").click()
                page.get_by_role("textbox", name="What were your key tasks for").fill(
                    form_responses["key_tasks"]
                )
                page.get_by_role("textbox", name="What challenges/problems did").fill(
                    form_responses["challenges"]
                )
                page.get_by_role("textbox", name="What challenges/problems you").fill(
                    form_responses["challenge_resolution"]
                )
                page.get_by_role("textbox", name="What is your plan for the").fill(
                    form_responses["tomorrow_plan"]
                )
                page.get_by_role("button", name="Next").click()
                page.get_by_role("button", name="Submit").click()
            case 3:
                page.get_by_role(
                    "radio",
                    name="It was a working day, but I was on leave or absent",
                ).click()
                page.get_by_role("button", name="Next").click()
                page.get_by_role("button", name="Submit").click()
            case _:
                raise FormUnavailableError("No valid work-day type is selected.")
        page.wait_for_function(
            """() => {
                const text = document.body.innerText.toLowerCase();
                return text.includes('response has been recorded')
                    || text.includes('response recorded')
                    || text.includes('thank you');
            }""",
            timeout=15000,
        )
    except SessionExpiredError:
        raise
    except PlaywrightTimeoutError as error:
        if _is_google_sign_in_page(page):
            raise SessionExpiredError(
                "Google session expired. Reconnect your Google account to submit the pending form."
            ) from error
        raise FormUnavailableError(
            "The Google Form could not be filled or did not confirm the submission."
        ) from error
    except PlaywrightError as error:
        raise AutomationError("The browser could not submit the Google Form.") from error
    finally:
        context.close()


def submit_form(
    work_day: int,
    form_responses: dict[str, str],
    user_id: str = LOCAL_PROFILE_ID,
    account_email: str = "",
) -> None:
    """Submit the form through the dedicated local Chromium profile."""
    with sync_playwright() as playwright:
        _fill_form(playwright, work_day, form_responses, user_id, account_email)

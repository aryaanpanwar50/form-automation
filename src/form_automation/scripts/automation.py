import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ..local_auth_state import profile_directory
from ..local_credentials import CredentialStoreError, get_google_password
from ..local_paths import APP_DATA_DIRECTORY, LOCAL_PROFILE_ID

FORM_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSc8RRUAG8n8nPB9dm21m_MxwHQ-JuDnEj7GnvwEkWXykkKFuQ"
    "/viewform"
)
ACCOUNT_CHECKBOX = "Record aryaan.panwar.s66@"
FORM_RADIO_OPTIONS = (
    ("Campus holiday", "It was a campus holiday"),
    ("Working day - present", "It was a working day, and I"),
    ("Working day - leave or absent", "It was a working day, but I was on leave or absent"),
)
DIAGNOSTICS_DIRECTORY = APP_DATA_DIRECTORY / "diagnostics"

logger = logging.getLogger("form_automation.automation")
ProgressReporter = Callable[[str], None]


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


def _report_stage(progress_reporter: ProgressReporter | None, stage: str) -> None:
    """Persist a human-readable run stage without recording form data or secrets."""
    logger.info("Automation stage: %s", stage)
    if progress_reporter:
        progress_reporter(stage)


def _start_failure_trace(context) -> bool:
    """Start an in-memory trace that is written only if the run fails."""
    tracing = getattr(context, "tracing", None)
    if tracing is None:
        return False
    tracing.start(screenshots=True, snapshots=True, sources=True)
    return True


def _save_failure_diagnostics(context, page, stage: str, trace_started: bool) -> str:
    """Save local failure evidence without allowing diagnostic errors to hide the cause."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_stage = "".join(
        character if character.isalnum() else "-" for character in stage.lower()
    ).strip("-")
    base_name = f"submission-failure-{stamp}-{safe_stage}"
    saved_files: list[str] = []

    try:
        DIAGNOSTICS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        screenshot_path = DIAGNOSTICS_DIRECTORY / f"{base_name}.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        saved_files.append(screenshot_path.name)
    except Exception:  # Diagnostics must never replace the useful failure message.
        logger.exception("Could not save submission failure screenshot")

    if trace_started:
        try:
            trace_path = DIAGNOSTICS_DIRECTORY / f"{base_name}.zip"
            context.tracing.stop(path=str(trace_path))
            saved_files.append(trace_path.name)
        except Exception:
            logger.exception("Could not save Playwright failure trace")

    if not saved_files:
        return ""
    return (
        " Diagnostic files saved locally in FormAutomation\\diagnostics: "
        + ", ".join(saved_files)
        + "."
    )


def _stop_success_trace(context, trace_started: bool) -> None:
    if trace_started:
        try:
            context.tracing.stop()
        except Exception:
            logger.exception("Could not stop Playwright trace")


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


def _require_visible_radio(page, radio_name: str, option_label: str) -> None:
    """Confirm a form option exists without clicking it."""
    try:
        visible = page.get_by_role("radio", name=radio_name).is_visible(timeout=15000)
    except PlaywrightTimeoutError as error:
        raise FormUnavailableError(
            f'The Google Form option "{option_label}" was not found.'
        ) from error
    if not visible:
        raise FormUnavailableError(
            f'The Google Form option "{option_label}" is not visible.'
        )


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
    progress_reporter: ProgressReporter | None = None,
) -> None:
    context = playwright.chromium.launch_persistent_context(
        str(profile_directory(user_id)), headless=True, channel="chromium"
    )
    page = context.pages[0] if context.pages else context.new_page()
    trace_started = False
    stage = "opening Google Form"

    try:
        trace_started = _start_failure_trace(context)
        _report_stage(progress_reporter, "Opening Google Form.")
        page.goto(FORM_URL, wait_until="domcontentloaded")
        stage = "checking Google session"
        _report_stage(progress_reporter, "Checking Google session.")
        _restore_session_if_needed(page, account_email, user_id)
        stage = "checking form account checkbox"
        _report_stage(progress_reporter, "Checking form account checkbox.")
        checkbox = _require_form_checkbox(page)
        if not checkbox.is_checked():
            stage = "selecting form account checkbox"
            _report_stage(progress_reporter, "Selecting form account checkbox.")
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
                stage = "selecting campus holiday"
                _report_stage(progress_reporter, "Selecting Campus holiday.")
                page.get_by_role("radio", name="It was a campus holiday").click()
                stage = "opening confirmation page"
                _report_stage(progress_reporter, "Opening confirmation page.")
                page.get_by_role("button", name="Next").click()
                stage = "submitting Google Form"
                _report_stage(progress_reporter, "Submitting Google Form.")
                page.get_by_role("button", name="Submit").click()
            case 2:
                stage = "selecting working day"
                _report_stage(progress_reporter, "Selecting Working day - present.")
                page.get_by_role("radio", name="It was a working day, and I").click()
                stage = "opening response page"
                _report_stage(progress_reporter, "Opening response page.")
                page.get_by_role("button", name="Next").click()
                stage = "filling key tasks"
                _report_stage(progress_reporter, "Filling key tasks.")
                page.get_by_role("textbox", name="What were your key tasks for").fill(
                    form_responses["key_tasks"]
                )
                stage = "filling challenges"
                _report_stage(progress_reporter, "Filling challenges.")
                page.get_by_role("textbox", name="What challenges/problems did").fill(
                    form_responses["challenges"]
                )
                stage = "filling challenge resolution"
                _report_stage(progress_reporter, "Filling challenge resolution.")
                page.get_by_role("textbox", name="What challenges/problems you").fill(
                    form_responses["challenge_resolution"]
                )
                stage = "filling tomorrow plan"
                _report_stage(progress_reporter, "Filling tomorrow plan.")
                page.get_by_role("textbox", name="What is your plan for the").fill(
                    form_responses["tomorrow_plan"]
                )
                stage = "opening confirmation page"
                _report_stage(progress_reporter, "Opening confirmation page.")
                page.get_by_role("button", name="Next").click()
                stage = "submitting Google Form"
                _report_stage(progress_reporter, "Submitting Google Form.")
                page.get_by_role("button", name="Submit").click()
            case 3:
                stage = "selecting leave or absence"
                _report_stage(progress_reporter, "Selecting Working day - leave or absent.")
                page.get_by_role(
                    "radio",
                    name="It was a working day, but I was on leave or absent",
                ).click()
                stage = "opening confirmation page"
                _report_stage(progress_reporter, "Opening confirmation page.")
                page.get_by_role("button", name="Next").click()
                stage = "submitting Google Form"
                _report_stage(progress_reporter, "Submitting Google Form.")
                page.get_by_role("button", name="Submit").click()
            case _:
                raise FormUnavailableError("No valid work-day type is selected.")
        stage = "confirming submitted response"
        _report_stage(progress_reporter, "Confirming submitted response.")
        page.wait_for_function(
            """() => {
                const text = document.body.innerText.toLowerCase();
                return text.includes('response has been recorded')
                    || text.includes('response recorded')
                    || text.includes('thank you');
            }""",
            timeout=15000,
        )
    except PlaywrightTimeoutError as error:
        if _is_google_sign_in_page(page):
            error_to_raise: AutomationError = SessionExpiredError(
                "Google session expired. Reconnect your Google account to submit the pending form."
            )
        else:
            error_to_raise = FormUnavailableError(
                "The Google Form could not be filled or did not confirm the submission."
            )
        diagnostics = _save_failure_diagnostics(context, page, stage, trace_started)
        raise type(error_to_raise)(
            f"Failed while {stage}. {error_to_raise}{diagnostics}"
        ) from error
    except AutomationError as error:
        diagnostics = _save_failure_diagnostics(context, page, stage, trace_started)
        raise type(error)(f"Failed while {stage}. {error}{diagnostics}") from error
    except PlaywrightError as error:
        diagnostics = _save_failure_diagnostics(context, page, stage, trace_started)
        raise AutomationError(
            f"Failed while {stage}. The browser could not submit the Google Form.{diagnostics}"
        ) from error
    else:
        _stop_success_trace(context, trace_started)
    finally:
        context.close()


def _check_form_connection(
    playwright: Playwright,
    user_id: str = LOCAL_PROFILE_ID,
    account_email: str = "",
    progress_reporter: ProgressReporter | None = None,
) -> str:
    """Verify the saved account and all form controls without changing the form."""
    context = playwright.chromium.launch_persistent_context(
        str(profile_directory(user_id)), headless=True, channel="chromium"
    )
    page = context.pages[0] if context.pages else context.new_page()
    trace_started = False
    stage = "opening Google Form"

    try:
        trace_started = _start_failure_trace(context)
        _report_stage(progress_reporter, "Opening Google Form for connection test.")
        page.goto(FORM_URL, wait_until="domcontentloaded")
        stage = "checking Google session"
        _report_stage(progress_reporter, "Checking Google session.")
        _restore_session_if_needed(page, account_email, user_id)
        stage = "checking form account checkbox"
        _report_stage(progress_reporter, "Checking form account checkbox.")
        _require_form_checkbox(page)
        for option_label, radio_name in FORM_RADIO_OPTIONS:
            stage = f"checking {option_label.lower()} option"
            _report_stage(progress_reporter, f"Checking {option_label} option.")
            _require_visible_radio(page, radio_name, option_label)
    except PlaywrightTimeoutError as error:
        if _is_google_sign_in_page(page):
            error_to_raise: AutomationError = SessionExpiredError(
                "Google session expired. Reconnect your Google account to test the form."
            )
        else:
            error_to_raise = FormUnavailableError(
                "The Google Form could not be loaded during the connection test."
            )
        diagnostics = _save_failure_diagnostics(context, page, stage, trace_started)
        raise type(error_to_raise)(
            f"Failed while {stage}. {error_to_raise}{diagnostics}"
        ) from error
    except AutomationError as error:
        diagnostics = _save_failure_diagnostics(context, page, stage, trace_started)
        raise type(error)(f"Failed while {stage}. {error}{diagnostics}") from error
    except PlaywrightError as error:
        diagnostics = _save_failure_diagnostics(context, page, stage, trace_started)
        raise AutomationError(
            f"Failed while {stage}. The browser could not test the Google Form.{diagnostics}"
        ) from error
    else:
        _stop_success_trace(context, trace_started)
        _report_stage(progress_reporter, "Form connection test passed. No response was submitted.")
        return "Form connection test passed. No response was submitted."
    finally:
        context.close()


def submit_form(
    work_day: int,
    form_responses: dict[str, str],
    user_id: str = LOCAL_PROFILE_ID,
    account_email: str = "",
    progress_reporter: ProgressReporter | None = None,
) -> None:
    """Submit the form through the dedicated local Chromium profile."""
    with sync_playwright() as playwright:
        _fill_form(
            playwright,
            work_day,
            form_responses,
            user_id,
            account_email,
            progress_reporter,
        )


def test_form_connection(
    user_id: str = LOCAL_PROFILE_ID,
    account_email: str = "",
    progress_reporter: ProgressReporter | None = None,
) -> str:
    """Run the non-submitting connection test using the dedicated browser profile."""
    with sync_playwright() as playwright:
        return _check_form_connection(
            playwright, user_id, account_email, progress_reporter
        )

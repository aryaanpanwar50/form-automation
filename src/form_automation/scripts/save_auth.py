from playwright.sync_api import sync_playwright

from ..local_auth_state import save_local_auth_state
from ..local_paths import LOCAL_PROFILE_ID

FORM_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSc8RRUAG8n8nPB9dm21m_MxwHQ-JuDnEj7GnvwEkWXykkKFuQ"
    "/viewform"
)


def save_auth_for_user(user_id: str = LOCAL_PROFILE_ID) -> None:
    """Open a visible browser and save the signed-in Google Form session locally."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()

        try:
            page = context.new_page()
            page.goto(FORM_URL)
            print("Sign in to the Google account that should submit the form.")
            print("The session will save automatically after the form opens.")
            page.wait_for_function(
                """() => location.hostname === 'docs.google.com'
                    && location.pathname.includes('/forms/d/e/')
                    && document.querySelector('form') !== null""",
                timeout=300000,
            )
            save_local_auth_state(user_id, context.storage_state())
            print("Encrypted Google session saved on this PC.")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    save_auth_for_user()

from playwright.sync_api import sync_playwright

from ..local_auth_state import clear_local_auth_state, mark_local_auth_profile, profile_directory
from ..local_paths import LOCAL_PROFILE_ID

FORM_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSc8RRUAG8n8nPB9dm21m_MxwHQ-JuDnEj7GnvwEkWXykkKFuQ"
    "/viewform"
)


def save_auth_for_user(user_id: str = LOCAL_PROFILE_ID) -> None:
    """Open the app's persistent Chromium profile and save a signed-in session."""
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_directory(user_id)), headless=False, channel="chromium"
        )

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
            mark_local_auth_profile(user_id)
            clear_local_auth_state(user_id)
            print("Google profile saved on this PC.")
        finally:
            context.close()


if __name__ == "__main__":
    save_auth_for_user()

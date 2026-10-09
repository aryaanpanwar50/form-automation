from playwright.sync_api import Playwright, sync_playwright

FORM_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSc8RRUAG8n8nPB9dm21m_MxwHQ-JuDnEj7GnvwEkWXykkKFuQ"
    "/viewform"
)


def _fill_form(
    playwright: Playwright,
    work_day: int,
    storage_state: dict,
    form_responses: dict[str, str],
) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(storage_state=storage_state)

    try:
        page = context.new_page()
        page.goto(FORM_URL, wait_until="domcontentloaded")

        checkbox = page.get_by_role("checkbox", name="Record aryaan.panwar.s66@")
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
            case 2:
                page.get_by_role("radio", name="It was a working day, and I").click()
            case 3:
                page.get_by_role(
                    "radio",
                    name="It was a working day, but I was on leave or absent",
                ).click()
            case _:
                raise ValueError(f"Invalid work_day: {work_day}")

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
        page.wait_for_function(
            """() => {
                const text = document.body.innerText.toLowerCase();
                return text.includes('response has been recorded')
                    || text.includes('response recorded')
                    || text.includes('thank you');
            }""",
            timeout=15000,
        )
    finally:
        context.close()
        browser.close()


def submit_form(
    work_day: int, storage_state: dict, form_responses: dict[str, str]
) -> None:
    """Run the Playwright workflow with an in-memory, user-specific session."""
    with sync_playwright() as playwright:
        _fill_form(playwright, work_day, storage_state, form_responses)

# Form Automation

A local Python desktop app that schedules the existing Google Form workflow on this PC.
The app has no cloud database or app-account sign-in. Google is contacted only for the
Google Form and its sign-in session.

## What it does

- Runs a scheduled Google Form submission locally on weekdays.
- Uses a dedicated Chromium profile for the Google account connected in the app.
- Records the selected Google account email with the response when the form exposes the
  **Record ... as the email to be included with my response** checkbox.
- Supports one default work-day type and date-specific calendar overrides:
  **Campus holiday**, **Working day · present**, or **Working day · leave or absent**.
- Saves one pending task locally so an eligible task can run after the PC wakes later on
  the same day.

The app marks a task complete only after the Google Forms page explicitly says
**Your response has been recorded**. A generic "Thank you" message is not treated as a
successful submission.


## Run it

Install Python 3.14 and `uv`, then from this folder run:

```powershell
uv sync
uv run playwright install chromium --no-shell
uv run form-automation
```

The first run opens a native desktop window. Choose **Connect Google account**, sign in
in the Chromium window, and wait for the form to load. The app saves a dedicated local
Chromium profile for this workflow; it never saves your Google password. Choose a
work-day answer and time, edit the four response fields, then enable the schedule with
the checkbox. These settings save automatically.

The app runs the job locally from Monday to Friday while it is open or minimized to
the Windows system tray. The work-day answer and time save automatically when changed.
At submission time, Chromium opens on this PC and runs the form workflow. Closing the
app from the tray stops scheduled jobs; starting the app again restores the saved
schedule from local settings.

Use **Start Form Automation when I sign in** only if you want the local scheduler to
start automatically after a restart. This is disabled by default and uses a per-user
startup entry; it does not require administrator access.

One pending task is saved locally. If the PC sleeps through its scheduled time, the app
runs that task after wake if it is still the same calendar day. At midnight, an older
pending task expires; the next task follows the regular daily schedule.

## Calendar overrides

The Calendar tab changes the work-day type for one specific date; it does not submit a
form immediately. Select a date, choose an option, then click **Save**. The saved
override takes priority over the Home tab's default for that date.

At the scheduled time, the app reads the queued date's override and follows the matching
form path:

| Calendar value | Form action |
| --- | --- |
| Campus holiday | Selects the campus-holiday answer, then submits. |
| Working day · present | Selects present, fills the four response fields, then submits. |
| Working day · leave or absent | Selects leave/absent, then submits. |

Scheduled submissions run Monday through Friday. Keep the app running or minimized to
the system tray at the scheduled time. The calendar override must be saved before the
job runs.

## Local files

Settings, the dedicated browser profile, legacy encrypted session data, and logs are
stored under:

```text
%LOCALAPPDATA%\FormAutomation
```

On macOS, files are stored under:

```text
~/Library/Application Support/FormAutomation
```

The schedule, form responses, and the latest submission status are stored in a local
`settings.json` file. If Google signs the profile out or a form control changes, the app
keeps the pending task and shows a tray and in-app error message. No database, cloud
database, or remote app server is used.

### Troubleshooting a submission

Check the in-app status first. It identifies the last completed stage, such as checking
the Google session, checking the account checkbox, selecting an answer, or confirming
the submitted response.

For a failed run, inspect:

```text
%LOCALAPPDATA%\FormAutomation\form-automation.log
%LOCALAPPDATA%\FormAutomation\diagnostics\
```

The diagnostics folder contains a screenshot and Playwright trace for failed runs. Open
a trace on a development machine with:

```powershell
uv run playwright show-trace path\to\submission-failure-....zip
```

The screenshot and trace can contain form content and the signed-in account email. Do
not publish them or share the dedicated browser-profile directory.

## Build a Windows executable

The GitHub Actions workflow at `.github/workflows/windows.yml` runs the Windows unit
tests on pushes and pull requests. On pushes and manual runs, it builds a Windows x64
app bundle and uploads `FormAutomation-windows-x64.zip` and
`FormAutomation-Setup-windows-x64.exe` as workflow artifacts. Pushing a version tag
such as `v0.2.8` also creates a GitHub Release with the installer attached. Create the
version tag only after the intended commits, `pyproject.toml` version, and `uv.lock` are
on `main`; release builds use the commit referenced by the tag.

The zip contains the standalone executable, its Qt/Python dependencies, and the
Playwright Chromium browser. Extract the full folder before running
`FormAutomation.exe`; the browser folder must remain beside the executable. The first
launch creates local app data under `%LOCALAPPDATA%\FormAutomation`.

Alternatively, run `FormAutomation-Setup-windows-x64.exe` to install the app for the
current Windows user without administrator access. The installer creates a Start Menu
shortcut and can optionally create a desktop shortcut. Uninstalling removes the app
and its sign-in startup entry but leaves local settings and the dedicated Google
profile under `%LOCALAPPDATA%\FormAutomation`.

To build locally on Windows with the MSVC build tools installed:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\ms-playwright"
uv sync --locked
uv pip install --python .venv\Scripts\python.exe pip
uv run playwright install chromium --no-shell
uv run python scripts\generate_windows_icon.py
uv run pyside6-deploy run_app.py --name FormAutomation --mode standalone --force
Copy-Item .\ms-playwright .\FormAutomation.dist\ms-playwright -Recurse
```

## Build a macOS DMG

The `.github/workflows/macos.yml` workflow tests Apple Silicon (`arm64`). On pushes and
manual runs, it builds a native `.app`, embeds matching Playwright Chromium inside the
app bundle, and uploads:

- `FormAutomation-macos-arm64.dmg`

The DMGs are currently unsigned. Before public distribution, they should be signed and
notarized with an Apple Developer certificate; otherwise macOS will show an unidentified
developer warning on first open.

# Form Automation

A local Python desktop app that schedules the existing Google Form workflow on this PC.
The app has no cloud database or app-account sign-in. Google is contacted only for the
Google Form and its sign-in session.

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

## Build a Windows executable

The GitHub Actions workflow at `.github/workflows/windows.yml` runs the Windows unit
tests on pushes and pull requests. On pushes and manual runs, it builds a Windows x64
app bundle and uploads `FormAutomation-windows-x64.zip` and
`FormAutomation-Setup-windows-x64.exe` as workflow artifacts. Pushing a version tag
such as `v0.1.0` also creates a GitHub Release with both files attached.

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

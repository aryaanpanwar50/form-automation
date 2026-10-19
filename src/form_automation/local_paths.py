import os
from pathlib import Path


APP_DATA_DIRECTORY = Path(
    os.getenv("LOCALAPPDATA", Path.home() / ".local" / "share")
) / "FormAutomation"
LOCAL_PROFILE_ID = "default"
GOOGLE_PROFILE_DIRECTORY = APP_DATA_DIRECTORY / "google-profile"

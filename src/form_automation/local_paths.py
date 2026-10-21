from pathlib import Path

from .platform_services import AppPaths


APP_DATA_DIRECTORY = AppPaths.create().app_data_directory
LOCAL_PROFILE_ID = "default"
GOOGLE_PROFILE_DIRECTORY = APP_DATA_DIRECTORY / "google-profile"

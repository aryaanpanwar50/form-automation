import json
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .local_paths import APP_DATA_DIRECTORY

KEY_FILE = APP_DATA_DIRECTORY / "playwright-state.key"


def _cipher() -> Fernet:
    APP_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(Fernet.generate_key())

    return Fernet(KEY_FILE.read_bytes())


def _state_file(user_id: str) -> Path:
    safe_user_id = re.sub(r"[^a-zA-Z0-9_-]", "_", user_id)
    return APP_DATA_DIRECTORY / f"google-session-{safe_user_id}.bin"


def save_local_auth_state(user_id: str, storage_state: dict) -> None:
    encrypted_state = _cipher().encrypt(json.dumps(storage_state).encode())
    _state_file(user_id).write_bytes(encrypted_state)


def get_local_auth_state(user_id: str) -> dict | None:
    state_file = _state_file(user_id)
    if not state_file.exists():
        return None

    try:
        decrypted_state = _cipher().decrypt(state_file.read_bytes()).decode()
    except InvalidToken as error:
        raise RuntimeError("Stored Google session could not be decrypted") from error

    return json.loads(decrypted_state)


def has_local_auth_state(user_id: str) -> bool:
    return _state_file(user_id).is_file()


def clear_local_auth_state(user_id: str) -> None:
    _state_file(user_id).unlink(missing_ok=True)

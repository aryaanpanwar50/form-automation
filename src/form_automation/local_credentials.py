"""Operating-system credential vault wrapper for the optional Google password.

The application never writes this password to settings.json, the Chromium profile,
or application logs. Windows Credential Manager and macOS Keychain encrypt it for
the current user.
"""

from __future__ import annotations

import ctypes
import os
import platform
import re
from ctypes import wintypes

from .platform_services import MacOSKeychainCredentialStore


class CredentialStoreError(RuntimeError):
    """Windows Credential Manager could not store or read a credential."""


_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_LPBYTE = ctypes.POINTER(ctypes.c_ubyte)


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", ctypes.c_byte * 8),  # FILETIME; not used by this app.
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", _LPBYTE),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_CredentialPointer = ctypes.POINTER(_Credential)


def _target_name(user_id: str) -> str:
    safe_user_id = re.sub(r"[^a-zA-Z0-9_-]", "_", user_id)
    return f"FormAutomation.GooglePassword.{safe_user_id}"


def _credential_api():
    if os.name != "nt":
        raise CredentialStoreError("Automatic reconnect is available only on Windows.")
    api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    api.CredWriteW.argtypes = [_CredentialPointer, wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_CredentialPointer),
    ]
    api.CredReadW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api


def _raise_credential_error(action: str) -> None:
    error_code = ctypes.get_last_error()
    raise CredentialStoreError(
        f"Windows Credential Manager could not {action} the automatic reconnect password "
        f"(error {error_code})."
    )


def save_google_password(user_id: str, password: str) -> None:
    """Save a non-empty password in the current OS credential vault."""
    if platform.system() == "Darwin":
        try:
            MacOSKeychainCredentialStore().save(user_id, password)
        except RuntimeError as error:
            raise CredentialStoreError(str(error)) from error
        return
    if not password:
        raise ValueError("Password cannot be empty")
    encoded_password = password.encode("utf-16-le")
    password_buffer = ctypes.create_string_buffer(encoded_password)
    credential = _Credential()
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = _target_name(user_id)
    credential.CredentialBlobSize = len(encoded_password)
    credential.CredentialBlob = ctypes.cast(password_buffer, _LPBYTE)
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = user_id
    if not _credential_api().CredWriteW(ctypes.byref(credential), 0):
        _raise_credential_error("save")


def get_google_password(user_id: str) -> str | None:
    """Return the saved password, or None when automatic reconnect is not enabled."""
    if platform.system() == "Darwin":
        try:
            return MacOSKeychainCredentialStore().get(user_id)
        except RuntimeError as error:
            raise CredentialStoreError(str(error)) from error
    credential_pointer = _CredentialPointer()
    api = _credential_api()
    if not api.CredReadW(
        _target_name(user_id), _CRED_TYPE_GENERIC, 0, ctypes.byref(credential_pointer)
    ):
        # ERROR_NOT_FOUND means the user has not enabled the optional feature.
        if ctypes.get_last_error() == 1168:
            return None
        _raise_credential_error("read")
    try:
        credential = credential_pointer.contents
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return blob.decode("utf-16-le")
    finally:
        api.CredFree(credential_pointer)


def clear_google_password(user_id: str) -> None:
    """Remove the optional reconnect password.  Missing credentials are harmless."""
    if platform.system() == "Darwin":
        try:
            MacOSKeychainCredentialStore().clear(user_id)
        except RuntimeError as error:
            raise CredentialStoreError(str(error)) from error
        return
    if not _credential_api().CredDeleteW(_target_name(user_id), _CRED_TYPE_GENERIC, 0):
        if ctypes.get_last_error() != 1168:
            _raise_credential_error("remove")

